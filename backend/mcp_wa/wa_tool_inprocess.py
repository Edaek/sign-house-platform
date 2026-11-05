"""Execute WA MCP tools in-process (no HTTP JWT) — WhatsApp Loomy classify path."""
from __future__ import annotations

import json
from typing import Any

from bson import ObjectId

from mcp_wa.client import json_result


def _db():
    from app import mongo

    return mongo.db

INPROCESS_TOOL_NAMES = frozenset({
    'wa_get_nas_status',
    'wa_get_pool_stats',
    'wa_list_pool_images',
    'wa_list_projects',
    'wa_get_project',
    'wa_assign_pool_images',
    'wa_append_site_remark',
    'wa_rename_site_remark_txt',
    'wa_read_site_remark_txt',
    'wa_set_site_remark_txt',
    'wa_delete_site_remark_txt',
    'wa_list_keywords',
    'wa_get_record',
})


def inprocess_tools_enabled() -> bool:
    import os

    raw = (os.environ.get('LOOMY_WA_INPROCESS_TOOLS') or 'true').strip().lower()
    return raw in ('1', 'true', 'yes', 'on')


def can_run_inprocess(name: str) -> bool:
    return inprocess_tools_enabled() and name in INPROCESS_TOOL_NAMES


def execute_tool_inprocess(name: str, arguments: dict[str, Any]) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    fn = _HANDLERS.get(name)
    if not fn:
        return f'Error: no in-process handler for {name}'
    return fn(args)


def _exec_nas_status(_a: dict) -> str:
    from app.services.nas_watcher_service import nas_mount
    from app.services.nas_sync_service import get_last_nas_sync_status

    data = dict(nas_mount.status())
    last = get_last_nas_sync_status()
    if last.get('at'):
        data['lastAutoSyncAt'] = last.get('at')
        data['lastProjectsCreated'] = last.get('projectsCreated', [])
        data['lastRecordsImported'] = last.get('recordsImported', 0)
    try:
        from flask import current_app

        data['autoSyncIntervalSec'] = current_app.config.get('NAS_SYNC_INTERVAL_S', 60)
    except RuntimeError:
        pass
    return json_result(data)


def _exec_pool_stats(_a: dict) -> str:
    from app.models import serialize_doc

    pipeline = [
        {'$match': {'projectId': {'$exists': False}, 'dismissed': {'$ne': True}}},
        {'$group': {'_id': '$phone', 'count': {'$sum': 1},
                   'senderName': {'$first': '$senderName'},
                   'latestAt': {'$max': '$createdAt'}}},
        {'$sort': {'latestAt': -1}},
    ]
    db = _db()
    by_sender = list(db.pool_images.aggregate(pipeline))
    return json_result({
        'totalUnassigned': db.pool_images.count_documents({'projectId': {'$exists': False}, 'dismissed': {'$ne': True}}),
        'totalAssigned': db.pool_images.count_documents({'projectId': {'$exists': True}}),
        'bySender': [serialize_doc(s) for s in by_sender],
    })


def _exec_list_pool(a: dict) -> str:
    from app.services.pool_receipt_notify_service import phone_match_query

    status = a.get('status') or 'unassigned'
    phone = (a.get('phone') or '').strip()
    project_filter = (a.get('project') or '').strip()
    page = max(1, int(a.get('page') or 1))
    limit = min(100, max(1, int(a.get('limit') or 50)))

    query: dict[str, Any] = {}
    if status == 'unassigned':
        query['projectId'] = {'$exists': False}
        query['dismissed'] = {'$ne': True}
    elif status == 'assigned':
        query['projectId'] = {'$exists': True}
    if phone:
        query.update(phone_match_query(phone))
    if project_filter:
        query['projectId'] = ObjectId(project_filter)

    db = _db()
    total = db.pool_images.count_documents(query)
    skip = (page - 1) * limit
    images = list(
        db.pool_images.find(query).sort('createdAt', -1).skip(skip).limit(limit),
    )
    from app.models import serialize_doc

    payload = {
        'images': [serialize_doc(img) for img in images],
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'pages': (total + limit - 1) // limit if limit else 1,
        },
    }
    if status == 'unassigned' and images:
        from app.services.loom_turn_claim_service import (
            claim_loom_inbound_turn,
            pool_image_ids_for_turn_claim,
            pool_inbound_turn_anchor_ids,
        )

        payload.update(
            claim_loom_inbound_turn(
                image_ids=pool_image_ids_for_turn_claim(images),
                wa_message_ids=pool_inbound_turn_anchor_ids(images),
            ),
        )
    return json_result(payload)


def _exec_list_projects(a: dict) -> str:
    from app.models import serialize_doc
    from app.services.nas_sync_service import enrich_wa_projects_display
    from app.services.project_number_match_service import (
        list_wa_classify_target_projects,
        wa_classify_display_label,
    )

    status = (a.get('status') or 'active').strip().lower()
    active_only = status != 'all'
    projects = list_wa_classify_target_projects(active_only=active_only, limit=120)
    enrich_wa_projects_display(projects)
    rows = []
    for p in projects:
        row = serialize_doc(p)
        row['displayLabel'] = wa_classify_display_label(p, max_len=400)
        rows.append(row)
    return json_result({'projects': rows})


def _exec_get_project(a: dict) -> str:
    pid = (a.get('project_id') or '').strip()
    if not pid:
        return 'Error: project_id required'
    try:
        oid = ObjectId(pid)
    except Exception:
        return 'Error: invalid project_id'
    from app.models import serialize_doc

    project = _db().wa_projects.find_one({'_id': oid})
    if not project:
        return 'Error: project not found'
    return json_result(serialize_doc(project))


def _exec_assign_pool(a: dict) -> str:
    ids = a.get('image_ids') or a.get('imageIds') or []
    if isinstance(ids, str):
        ids = [ids]
    pid = (a.get('project_id') or a.get('projectId') or '').strip()
    if not ids or not pid:
        return 'Error: image_ids and project_id required'

    project = _db().wa_projects.find_one({'_id': ObjectId(pid)})
    if not project:
        return json_result({'error': 'Project not found', 'assigned': 0})
    if project.get('status') != 'active':
        return json_result({'error': 'Project must be active', 'assigned': 0})

    from app.services.image_pool_service import assign_images_to_project

    proj = dict(project)
    fn = (a.get('nas_folder_name') or a.get('nasFolderName') or '').strip()
    pb = (a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip()
    if fn:
        proj['nasFolderName'] = fn
    if pb:
        proj['nasParentBucket'] = pb
    group_id = (a.get('group_id') or a.get('groupId') or '').strip() or None
    notify = bool(a.get('notify_whatsapp') or a.get('notifyWhatsApp'))
    from app.services.wa_classify_mode import wa_loom_runtime_brain_enabled

    if wa_loom_runtime_brain_enabled():
        notify = False
    phone = (a.get('phone') or '').strip() or None
    remark = (a.get('remark') or '').strip() or None

    try:
        count = assign_images_to_project(
            ids, proj, 'loomy_agent', remark=remark, group_id=group_id,
        )
    except ValueError as exc:
        from app.services.loomy_pool_batch import PoolAssignNotClassifyTargetError

        if isinstance(exc, PoolAssignNotClassifyTargetError):
            return json_result({
                'error': str(exc),
                'assigned': 0,
                'code': 'not_classify_target',
            })
        raise
    return json_result({
        'assigned': count,
        'projectCode': project.get('code'),
        'whatsappNotified': False,
        'remark': remark,
        'siteRemarkQueued': bool(remark),
    })


def _exec_append_site_remark(a: dict) -> str:
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    text = (a.get('text') or a.get('remark') or '').strip()
    if not code or not text:
        return 'Error: project_code and text required'
    from app.services.nas_site_remark_service import (
        append_site_remark_to_nas,
        _merge_remark_into_latest_record,
    )

    remark_file = (a.get('remark_filename') or a.get('remarkFilename') or '').strip() or None
    result = append_site_remark_to_nas(
        code,
        text,
        day_str=(a.get('day') or '').strip() or None,
        preferred_folder_name=(a.get('nas_folder_name') or a.get('nasFolderName') or '').strip() or None,
        preferred_parent_bucket=(a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip() or None,
        preferred_remark_filename=remark_file,
        fallback_to_canonical_if_missing=bool(a.get('fallback_to_canonical')),
    )
    phone = (a.get('phone') or '').strip()
    group_id = (a.get('group_id') or a.get('groupId') or '').strip() or None
    if phone and result.get('ok') and not result.get('skipped'):
        _merge_remark_into_latest_record(phone, text, code, group_id=group_id)
    return json_result(result)


def _exec_rename_site_remark_txt(a: dict) -> str:
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    new_name = (a.get('new_filename') or a.get('newFilename') or '').strip()
    if not code or not new_name:
        return 'Error: project_code and new_filename required'
    from app.services.nas_site_remark_service import (
        rename_site_remark_txt,
        set_site_remark_context,
        hk_today_str,
    )

    result = rename_site_remark_txt(
        code,
        new_name,
        day_str=(a.get('day') or '').strip() or None,
        old_filename=(a.get('old_filename') or a.get('oldFilename') or '').strip() or None,
        preferred_folder_name=(a.get('nas_folder_name') or a.get('nasFolderName') or '').strip() or None,
        preferred_parent_bucket=(a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip() or None,
    )
    phone = (a.get('phone') or '').strip()
    group_id = (a.get('group_id') or a.get('groupId') or '').strip() or None
    day = (a.get('day') or '').strip() or None
    if phone and result.get('ok') and result.get('fileName') and not result.get('unchanged'):
        set_site_remark_context(
            phone,
            code,
            group_id=group_id,
            day_str=day or hk_today_str(),
            nas_folder_name=(a.get('nas_folder_name') or a.get('nasFolderName') or '').strip() or None,
            nas_parent_bucket=(a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip() or None,
            remark_file_name=result['fileName'],
        )
    return json_result(result)


def _exec_read_site_remark_txt(a: dict) -> str:
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    if not code:
        return 'Error: project_code required'
    from app.services.nas_site_remark_service import read_site_remark_txt

    result = read_site_remark_txt(
        code,
        day_str=(a.get('day') or '').strip() or None,
        filename=(a.get('filename') or a.get('fileName') or '').strip() or None,
        preferred_folder_name=(a.get('nas_folder_name') or a.get('nasFolderName') or '').strip() or None,
        preferred_parent_bucket=(a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip() or None,
        list_all=bool(a.get('list_all') or a.get('listAll')),
    )
    return json_result(result)


def _exec_set_site_remark_txt(a: dict) -> str:
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    if not code:
        return 'Error: project_code required'
    if 'content' not in a and 'text' not in a:
        return 'Error: content required'
    from app.services.nas_site_remark_service import set_site_remark_txt

    content = a.get('content')
    if content is None:
        content = a.get('text')
    result = set_site_remark_txt(
        code,
        '' if content is None else str(content),
        day_str=(a.get('day') or '').strip() or None,
        filename=(a.get('filename') or a.get('fileName') or '').strip() or None,
        preferred_folder_name=(a.get('nas_folder_name') or a.get('nasFolderName') or '').strip() or None,
        preferred_parent_bucket=(a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip() or None,
        create_if_missing=bool(a.get('create_if_missing') or a.get('createIfMissing')),
        delete_file=bool(a.get('delete_file') or a.get('deleteFile')),
    )
    return json_result(result)


def _exec_delete_site_remark_txt(a: dict) -> str:
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    if not code:
        return 'Error: project_code required'
    from app.services.nas_site_remark_service import delete_site_remark_txt

    result = delete_site_remark_txt(
        code,
        day_str=(a.get('day') or '').strip() or None,
        filename=(a.get('filename') or a.get('fileName') or '').strip() or None,
        preferred_folder_name=(a.get('nas_folder_name') or a.get('nasFolderName') or '').strip() or None,
        preferred_parent_bucket=(a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip() or None,
    )
    return json_result(result)


def _exec_list_keywords(_a: dict) -> str:
    from app.models import serialize_doc

    keywords = list(_db().wa_keywords.find({'isActive': True}).sort('term', 1))
    return json_result({'keywords': [serialize_doc(k) for k in keywords]})


def _exec_get_record(a: dict) -> str:
    from app.models import serialize_doc

    rid = (a.get('record_id') or '').strip()
    if not rid:
        return 'Error: record_id required'
    record = _db().wa_records.find_one({'_id': ObjectId(rid)})
    if not record:
        return 'Error: record not found'
    return json_result(serialize_doc(record))


_HANDLERS = {
    'wa_get_nas_status': _exec_nas_status,
    'wa_get_pool_stats': _exec_pool_stats,
    'wa_list_pool_images': _exec_list_pool,
    'wa_list_projects': _exec_list_projects,
    'wa_get_project': _exec_get_project,
    'wa_assign_pool_images': _exec_assign_pool,
    'wa_append_site_remark': _exec_append_site_remark,
    'wa_rename_site_remark_txt': _exec_rename_site_remark_txt,
    'wa_read_site_remark_txt': _exec_read_site_remark_txt,
    'wa_set_site_remark_txt': _exec_set_site_remark_txt,
    'wa_delete_site_remark_txt': _exec_delete_site_remark_txt,
    'wa_list_keywords': _exec_list_keywords,
    'wa_get_record': _exec_get_record,
}
