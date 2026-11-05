"""WhatsApp Loomy: MCP tool metadata + allowlist + in-process execution."""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List

from mcp_wa.client import SignHouseApiError, SignHouseClient, json_result

ToolFn = Callable[[SignHouseClient, dict[str, Any]], str]

DEFAULT_DENY = frozenset({
    'wa_sync_nas_bidirectional',
    'wa_delete_project',
    'wa_delete_pool_images',
    'wa_confirm_record',
    'wa_void_record',
    'wa_create_project',
    'wa_request_record_info',
    'wa_create_nas_folder',
    'wa_sync_nas_projects',
    'wa_import_nas_files',
    'wa_import_nas_all',
    'wa_create_keyword',
    'wa_delete_keyword',
    'wa_create_template',
    'wa_send_message',
    'wa_send_media',
    'wa_send_group_message',
})

DEFAULT_ALLOW = frozenset({
    'wa_whoami',
    'wa_inbound_reply_policy',
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
    'wa_move_record_to_project',
    'wa_rename_nas_site_folder',
    'wa_sync_site_code_from_folder',
    'wa_get_whatsapp_status',
    'wa_get_infra_status',
    'wa_browse_nas',
    'wa_get_dashboard_stats',
    'wa_get_recent_records',
    'wa_search_records',
    'wa_list_project_records',
    'wa_get_record',
    'wa_update_record_field',
    'wa_list_keywords',
    'wa_list_templates',
    'wa_retry_pool_download',
    'wa_media_path_hint',
})


def _env_tool_set(key: str) -> frozenset[str]:
    raw = (os.environ.get(key) or '').strip()
    if not raw:
        return frozenset()
    return frozenset(x.strip() for x in raw.split(',') if x.strip())


def allowed_tools() -> frozenset[str]:
    extra_allow = _env_tool_set('LOOMY_WA_MCP_TOOLS_ALLOW')
    extra_deny = _env_tool_set('LOOMY_WA_MCP_TOOLS_DENY')
    base = set(DEFAULT_ALLOW) | set(extra_allow)
    base -= set(DEFAULT_DENY) | set(extra_deny)
    return frozenset(base)


def is_tool_allowed(name: str) -> bool:
    return name in allowed_tools()


def tool_catalog_for_prompt() -> str:
    lines = []
    for spec in TOOL_SPECS:
        if spec['name'] not in allowed_tools():
            continue
        lines.append(f"- {spec['name']}: {spec['description']} args={spec['args_hint']}")
    return '\n'.join(lines)


def _loom_brain_block_direct_wa_send(tool_name: str) -> str | None:
    if tool_name not in ('wa_send_message', 'wa_send_group_message', 'wa_send_media'):
        return None
    import os

    from app.services.wa_classify_mode import wa_loom_runtime_brain_enabled

    if not wa_loom_runtime_brain_enabled():
        return None
    raw = (os.environ.get('LOOMY_WA_MCP_BLOCK_DIRECT_SEND') or 'true').strip().lower()
    if raw in ('0', 'false', 'no', 'off'):
        return None
    return (
        f'Error: brain=loom — do not use {tool_name}; put worker text in Loom Turn reply only. '
        'Override: LOOMY_WA_MCP_BLOCK_DIRECT_SEND=false'
    )


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    client: SignHouseClient | None = None,
) -> str:
    if not is_tool_allowed(name):
        return f'Error: tool {name} is not allowed on WhatsApp worker channel.'
    blocked = _loom_brain_block_direct_wa_send(name)
    if blocked:
        return blocked
    args = arguments if isinstance(arguments, dict) else {}
    from mcp_wa.wa_tool_inprocess import can_run_inprocess, execute_tool_inprocess

    if can_run_inprocess(name):
        try:
            return execute_tool_inprocess(name, args)
        except Exception as exc:
            return f'Tool error: {exc}'
    fn = _EXECUTORS.get(name)
    if not fn:
        return f'Error: unknown tool {name}'
    if client is None:
        from mcp_wa.inprocess_client import try_get_inprocess_client

        client = try_get_inprocess_client()
        if client is None:
            return (
                f'Error: tool {name} requires HTTP API auth '
                '(SIGN_HOUSE_JWT or MCP_BOT_EMAIL/PASSWORD) or use in-process tools only.'
            )
    try:
        return fn(client, args)
    except SignHouseApiError as exc:
        return str(exc)
    except Exception as exc:
        return f'Tool error: {exc}'


def _exec_wa_get_nas_status(c: SignHouseClient, _a: dict) -> str:
    return json_result(c.get('/wa/nas/status'))


def _exec_wa_get_pool_stats(c: SignHouseClient, _a: dict) -> str:
    return json_result(c.get('/wa/image-pool', params={'mode': 'stats'}))


def _exec_wa_list_pool_images(c: SignHouseClient, a: dict) -> str:
    params = {
        'status': a.get('status') or 'unassigned',
        'phone': a.get('phone') or None,
        'project': a.get('project') or None,
        'page': int(a.get('page') or 1),
        'limit': int(a.get('limit') or 50),
    }
    return json_result(c.get('/wa/image-pool', params=params))


def _exec_wa_list_projects(c: SignHouseClient, a: dict) -> str:
    return json_result(c.get('/wa/projects', params={'status': a.get('status') or None}))


def _exec_wa_get_project(c: SignHouseClient, a: dict) -> str:
    pid = (a.get('project_id') or '').strip()
    if not pid:
        return 'Error: project_id required'
    inc = a.get('include_nas_files') in (True, 'true', '1', 1)
    return json_result(c.get(f'/wa/projects/{pid}', params={'includeNasFiles': '1' if inc else None}))


def _exec_wa_assign_pool_images(c: SignHouseClient, a: dict) -> str:
    ids = a.get('image_ids') or a.get('imageIds') or []
    if isinstance(ids, str):
        ids = [ids]
    pid = (a.get('project_id') or a.get('projectId') or '').strip()
    if not ids or not pid:
        return 'Error: image_ids and project_id required'
    notify = bool(a.get('notify_whatsapp') or a.get('notifyWhatsApp'))
    try:
        from app.services.wa_classify_mode import wa_loom_runtime_brain_enabled

        if wa_loom_runtime_brain_enabled():
            notify = False
    except Exception:
        pass
    body: dict[str, Any] = {
        'imageIds': ids,
        'projectId': pid,
        'notifyWhatsApp': notify,
    }
    gid = (a.get('group_id') or a.get('groupId') or '').strip()
    if gid:
        body['groupId'] = gid
    fn = (a.get('nas_folder_name') or a.get('nasFolderName') or '').strip()
    pb = (a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip()
    if fn:
        body['nasFolderName'] = fn
    if pb:
        body['nasParentBucket'] = pb
    remark = (a.get('remark') or '').strip()
    if remark:
        body['remark'] = remark
    return json_result(c.post('/wa/image-pool/assign', json_body=body))


def _exec_wa_move_record_to_project(c: SignHouseClient, a: dict) -> str:
    ref = (a.get('record_reference') or a.get('recordReference') or a.get('record_id') or '').strip()
    code = (a.get('project_code') or a.get('projectCode') or a.get('target_project_code') or '').strip()
    if not ref or not code:
        return 'Error: record_reference and project_code required'
    body: dict[str, Any] = {
        'recordReference': ref,
        'targetProjectCode': code,
        'relocateNas': a.get('relocate_nas', a.get('relocateNas', True)),
    }
    fn = (a.get('nas_folder_name') or a.get('nasFolderName') or '').strip()
    pb = (a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip()
    if fn:
        body['nasFolderName'] = fn
    if pb:
        body['nasParentBucket'] = pb
    return json_result(c.post('/wa/image-pool/move', json_body=body))


def _exec_wa_sync_site_code_from_folder(c: SignHouseClient, a: dict) -> str:
    pid = (a.get('project_id') or a.get('projectId') or '').strip()
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    pb = (a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip()
    body: dict[str, Any] = {}
    if pid:
        body['projectId'] = pid
    if code:
        body['projectCode'] = code
    if pb:
        body['nasParentBucket'] = pb
    if not pid and not code:
        return 'Error: project_id or project_code required'
    return json_result(c.post('/wa/nas/sync-site-code-from-folder', json_body=body))


def _exec_wa_rename_nas_site_folder(c: SignHouseClient, a: dict) -> str:
    new_name = (a.get('new_folder_name') or a.get('newFolderName') or '').strip()
    if not new_name:
        return 'Error: new_folder_name required'
    body: dict[str, Any] = {
        'newFolderName': new_name,
        'syncNas': a.get('sync_nas', a.get('syncNas', True)),
    }
    pid = (a.get('project_id') or a.get('projectId') or '').strip()
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    pb = (a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip()
    nc = (a.get('new_code') or a.get('newCode') or '').strip()
    if pid:
        body['projectId'] = pid
    if code:
        body['projectCode'] = code
    if pb:
        body['nasParentBucket'] = pb
    if nc:
        body['newCode'] = nc
    if not pid and not code:
        return 'Error: project_id or project_code required'
    return json_result(c.post('/wa/nas/rename-site-folder', json_body=body))


def _exec_wa_append_site_remark(c: SignHouseClient, a: dict) -> str:
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    text = (a.get('text') or a.get('remark') or '').strip()
    if not code or not text:
        return 'Error: project_code and text required'
    body: dict[str, Any] = {'projectCode': code, 'text': text}
    fn = (a.get('nas_folder_name') or a.get('nasFolderName') or '').strip()
    pb = (a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip()
    phone = (a.get('phone') or '').strip()
    day = (a.get('day') or '').strip()
    if fn:
        body['nasFolderName'] = fn
    if pb:
        body['nasParentBucket'] = pb
    if phone:
        body['phone'] = phone
    if day:
        body['day'] = day
    return json_result(c.post('/wa/image-pool/site-remark', json_body=body))


def _exec_wa_rename_site_remark_txt(c: SignHouseClient, a: dict) -> str:
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    new_name = (a.get('new_filename') or a.get('newFilename') or '').strip()
    if not code or not new_name:
        return 'Error: project_code and new_filename required'
    body: dict[str, Any] = {'projectCode': code, 'newFilename': new_name}
    fn = (a.get('nas_folder_name') or a.get('nasFolderName') or '').strip()
    pb = (a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip()
    phone = (a.get('phone') or '').strip()
    day = (a.get('day') or '').strip()
    old = (a.get('old_filename') or a.get('oldFilename') or '').strip()
    if fn:
        body['nasFolderName'] = fn
    if pb:
        body['nasParentBucket'] = pb
    if phone:
        body['phone'] = phone
    if day:
        body['day'] = day
    if old:
        body['oldFilename'] = old
    return json_result(c.post('/wa/image-pool/site-remark/rename', json_body=body))


def _exec_wa_read_site_remark_txt(c: SignHouseClient, a: dict) -> str:
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    if not code:
        return 'Error: project_code required'
    body: dict[str, Any] = {'projectCode': code}
    fn = (a.get('nas_folder_name') or a.get('nasFolderName') or '').strip()
    pb = (a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip()
    day = (a.get('day') or '').strip()
    fname = (a.get('filename') or a.get('fileName') or '').strip()
    if fn:
        body['nasFolderName'] = fn
    if pb:
        body['nasParentBucket'] = pb
    if day:
        body['day'] = day
    if fname:
        body['filename'] = fname
    if a.get('list_all') or a.get('listAll'):
        body['listAll'] = True
    return json_result(c.post('/wa/image-pool/site-remark/read', json_body=body))


def _exec_wa_set_site_remark_txt(c: SignHouseClient, a: dict) -> str:
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    if not code:
        return 'Error: project_code required'
    if 'content' not in a and 'text' not in a:
        return 'Error: content required'
    content = a.get('content')
    if content is None:
        content = a.get('text')
    body: dict[str, Any] = {'projectCode': code, 'content': content}
    fn = (a.get('nas_folder_name') or a.get('nasFolderName') or '').strip()
    pb = (a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip()
    day = (a.get('day') or '').strip()
    fname = (a.get('filename') or a.get('fileName') or '').strip()
    if fn:
        body['nasFolderName'] = fn
    if pb:
        body['nasParentBucket'] = pb
    if day:
        body['day'] = day
    if fname:
        body['filename'] = fname
    if a.get('create_if_missing') or a.get('createIfMissing'):
        body['createIfMissing'] = True
    if a.get('delete_file') or a.get('deleteFile'):
        body['deleteFile'] = True
    return json_result(c.post('/wa/image-pool/site-remark/content', json_body=body))


def _exec_wa_delete_site_remark_txt(c: SignHouseClient, a: dict) -> str:
    code = (a.get('project_code') or a.get('projectCode') or '').strip()
    if not code:
        return 'Error: project_code required'
    body: dict[str, Any] = {'projectCode': code}
    fn = (a.get('nas_folder_name') or a.get('nasFolderName') or '').strip()
    pb = (a.get('nas_parent_bucket') or a.get('nasParentBucket') or '').strip()
    day = (a.get('day') or '').strip()
    fname = (a.get('filename') or a.get('fileName') or '').strip()
    if fn:
        body['nasFolderName'] = fn
    if pb:
        body['nasParentBucket'] = pb
    if day:
        body['day'] = day
    if fname:
        body['filename'] = fname
    return json_result(c.post('/wa/image-pool/site-remark/delete', json_body=body))


def _exec_wa_whoami(c: SignHouseClient, _a: dict) -> str:
    return json_result(c.get('/auth/me'))


def _exec_wa_inbound_reply_policy(c: SignHouseClient, a: dict) -> str:
    phone = (a.get('phone') or '').strip()
    if not phone:
        return 'Error: phone required'
    params: dict = {'phone': phone}
    gid = (a.get('group_id') or a.get('groupId') or '').strip()
    if gid:
        params['group_id'] = gid
    return json_result(c.get('/wa/loom/worker-reply-policy', params=params))


def _exec_wa_get_whatsapp_status(c: SignHouseClient, _a: dict) -> str:
    return json_result(c.get('/wa/admin/system/status'))


def _exec_wa_get_infra_status(c: SignHouseClient, _a: dict) -> str:
    return json_result(c.get('/wa/admin/system/infra'))


def _exec_wa_browse_nas(c: SignHouseClient, a: dict) -> str:
    return json_result(c.get('/wa/nas/browse', params={'code': a.get('code') or None}))


def _exec_wa_get_dashboard_stats(c: SignHouseClient, _a: dict) -> str:
    return json_result(c.get('/wa/dashboard/stats'))


def _exec_wa_get_recent_records(c: SignHouseClient, _a: dict) -> str:
    return json_result(c.get('/wa/dashboard/recent'))


def _exec_wa_search_records(c: SignHouseClient, a: dict) -> str:
    params = {
        'q': a.get('q') or '',
        'status': a.get('status') or '',
        'phone': a.get('phone') or '',
        'project': a.get('project') or '',
        'from': a.get('from_date') or a.get('from') or '',
        'to': a.get('to_date') or a.get('to') or '',
        'page': int(a.get('page') or 1),
        'limit': int(a.get('limit') or 50),
    }
    return json_result(c.get('/wa/search', params=params))


def _exec_wa_list_project_records(c: SignHouseClient, a: dict) -> str:
    pid = (a.get('project_id') or '').strip()
    if not pid:
        return 'Error: project_id required'
    params = {
        'status': a.get('status') or None,
        'type': a.get('record_type') or None,
        'phone': a.get('phone') or None,
        'page': int(a.get('page') or 1),
        'limit': int(a.get('limit') or 50),
        'includeVoided': '1' if a.get('include_voided') else None,
    }
    return json_result(c.get(f'/wa/projects/{pid}/records', params=params))


def _exec_wa_get_record(c: SignHouseClient, a: dict) -> str:
    rid = (a.get('record_id') or '').strip()
    if not rid:
        return 'Error: record_id required'
    return json_result(c.get(f'/wa/records/{rid}'))


def _exec_wa_update_record_field(c: SignHouseClient, a: dict) -> str:
    rid = (a.get('record_id') or '').strip()
    field = (a.get('field') or '').strip()
    value = a.get('value')
    if value is None:
        value = ''
    if not rid or not field:
        return 'Error: record_id and field required'
    return json_result(
        c.patch(f'/wa/records/{rid}', json_body={'field': field, 'value': str(value)}),
    )


def _exec_wa_list_keywords(c: SignHouseClient, _a: dict) -> str:
    return json_result(c.get('/wa/keywords'))


def _exec_wa_list_templates(c: SignHouseClient, _a: dict) -> str:
    return json_result(c.get('/wa/templates'))


def _exec_wa_retry_pool_download(c: SignHouseClient, a: dict) -> str:
    ids = a.get('image_ids') or []
    if isinstance(ids, str):
        ids = [ids]
    return json_result(c.post('/wa/image-pool/retry-download', json_body={'imageIds': ids}))


def _exec_wa_media_path_hint(c: SignHouseClient, a: dict) -> str:
    from mcp_wa.client import uploads_url

    path = (a.get('path') or a.get('image_path') or '').strip()
    return json_result({'url': uploads_url(path)})


_EXECUTORS: Dict[str, ToolFn] = {
    'wa_get_nas_status': _exec_wa_get_nas_status,
    'wa_get_pool_stats': _exec_wa_get_pool_stats,
    'wa_list_pool_images': _exec_wa_list_pool_images,
    'wa_list_projects': _exec_wa_list_projects,
    'wa_get_project': _exec_wa_get_project,
    'wa_assign_pool_images': _exec_wa_assign_pool_images,
    'wa_append_site_remark': _exec_wa_append_site_remark,
    'wa_rename_site_remark_txt': _exec_wa_rename_site_remark_txt,
    'wa_read_site_remark_txt': _exec_wa_read_site_remark_txt,
    'wa_set_site_remark_txt': _exec_wa_set_site_remark_txt,
    'wa_delete_site_remark_txt': _exec_wa_delete_site_remark_txt,
    'wa_move_record_to_project': _exec_wa_move_record_to_project,
    'wa_rename_nas_site_folder': _exec_wa_rename_nas_site_folder,
    'wa_sync_site_code_from_folder': _exec_wa_sync_site_code_from_folder,
    'wa_whoami': _exec_wa_whoami,
    'wa_inbound_reply_policy': _exec_wa_inbound_reply_policy,
    'wa_get_whatsapp_status': _exec_wa_get_whatsapp_status,
    'wa_get_infra_status': _exec_wa_get_infra_status,
    'wa_browse_nas': _exec_wa_browse_nas,
    'wa_get_dashboard_stats': _exec_wa_get_dashboard_stats,
    'wa_get_recent_records': _exec_wa_get_recent_records,
    'wa_search_records': _exec_wa_search_records,
    'wa_list_project_records': _exec_wa_list_project_records,
    'wa_get_record': _exec_wa_get_record,
    'wa_update_record_field': _exec_wa_update_record_field,
    'wa_list_keywords': _exec_wa_list_keywords,
    'wa_list_templates': _exec_wa_list_templates,
    'wa_retry_pool_download': _exec_wa_retry_pool_download,
    'wa_media_path_hint': _exec_wa_media_path_hint,
}

TOOL_SPECS: List[dict] = [
    {'name': 'wa_get_nas_status', 'description': 'NAS mount status', 'args_hint': '{}'},
    {'name': 'wa_get_pool_stats', 'description': 'Media pool stats', 'args_hint': '{}'},
    {
        'name': 'wa_list_pool_images',
        'description': 'List pool images',
        'args_hint': '{status, phone, page, limit}',
    },
    {'name': 'wa_list_projects', 'description': 'List WA projects', 'args_hint': '{status}'},
    {'name': 'wa_get_project', 'description': 'Get project by id', 'args_hint': '{project_id}'},
    {
        'name': 'wa_assign_pool_images',
        'description': 'Assign pool images to a project. Pass remark to save the note and write the NAS day .txt.',
        'args_hint': '{image_ids, project_id, remark, nas_folder_name, nas_parent_bucket, group_id, notify_whatsapp}',
    },
    {
        'name': 'wa_append_site_remark',
        'description': 'Append a site note to Photo/YYYY-MM-DD/<code>_date.txt after photos were already filed.',
        'args_hint': '{project_code, text, nas_folder_name, nas_parent_bucket, phone, day}',
    },
    {
        'name': 'wa_rename_site_remark_txt',
        'description': 'Rename day remark .txt (custom name ok); rejects duplicate basename in same Photo/day folder.',
        'args_hint': '{project_code, new_filename, old_filename, nas_folder_name, nas_parent_bucket, phone, day}',
    },
    {
        'name': 'wa_read_site_remark_txt',
        'description': 'Read NAS day remark .txt content; list_all if multiple files in Photo/day.',
        'args_hint': '{project_code, day, filename, nas_folder_name, nas_parent_bucket, list_all}',
    },
    {
        'name': 'wa_set_site_remark_txt',
        'description': 'Replace entire day remark .txt; empty content clears body but keeps file. delete_file=true removes file.',
        'args_hint': '{project_code, content, day, filename, nas_folder_name, nas_parent_bucket, create_if_missing, delete_file}',
    },
    {
        'name': 'wa_delete_site_remark_txt',
        'description': 'Delete a day remark .txt file on NAS.',
        'args_hint': '{project_code, day, filename, nas_folder_name, nas_parent_bucket}',
    },
    {
        'name': 'wa_move_record_to_project',
        'description': 'Move a filed record (SUB-… or id) and all its photos to another project; relocates NAS files.',
        'args_hint': '{record_reference, project_code, nas_folder_name, nas_parent_bucket, relocate_nas}',
    },
    {
        'name': 'wa_rename_nas_site_folder',
        'description': 'Rename site folder on NAS (admin/manager); same as Web Manage Projects sync rename.',
        'args_hint': '{new_folder_name, project_id, project_code, nas_parent_bucket, new_code, sync_nas}',
    },
    {
        'name': 'wa_sync_site_code_from_folder',
        'description': 'Set project code to match NAS folder name when folder was renamed without code sync.',
        'args_hint': '{project_id, project_code, nas_parent_bucket}',
    },
    {'name': 'wa_browse_nas', 'description': 'Browse NAS folders', 'args_hint': '{code}'},
    {'name': 'wa_whoami', 'description': 'Current API user', 'args_hint': '{}'},
    {
        'name': 'wa_inbound_reply_policy',
        'description': (
            'Call FIRST each WhatsApp turn. Returns workerWhatsAppPolicy.allowWorkerWhatsAppNow — '
            'false until wa_list_pool_images; forbids interim「收到/我去 pool」before MCP. '
            'No LOOM_WA_INBOUND_NOTIFY_URL required when Wakka→Loom.'
        ),
        'args_hint': '{phone, group_id?}',
    },
    {'name': 'wa_list_keywords', 'description': 'Type keywords', 'args_hint': '{}'},
    {'name': 'wa_search_records', 'description': 'Search records', 'args_hint': '{q, phone, project}'},
    {'name': 'wa_get_record', 'description': 'Get WA record by id', 'args_hint': '{record_id}'},
    {
        'name': 'wa_update_record_field',
        'description': 'Patch one field on WA record (follow-up)',
        'args_hint': '{record_id, field, value}',
    },
]
