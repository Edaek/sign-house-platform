import logging
import re

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from bson import ObjectId
from datetime import datetime
from app import mongo
from app.models import serialize_doc
from app.utils.permissions import require_role

logger = logging.getLogger(__name__)
wa_image_pool_bp = Blueprint('wa_image_pool', __name__)

@wa_image_pool_bp.route('', methods=['GET'])
@jwt_required()
def list_or_stats():
    mode = request.args.get('mode')
    if mode == 'stats':
        pipeline = [
            {'$match': {'projectId': {'$exists': False}, 'dismissed': {'$ne': True}}},
            {'$group': {'_id': '$phone', 'count': {'$sum': 1},
                       'senderName': {'$first': '$senderName'},
                       'latestAt': {'$max': '$createdAt'}}},
            {'$sort': {'latestAt': -1}}
        ]
        by_sender = list(mongo.db.pool_images.aggregate(pipeline))
        total_unassigned = mongo.db.pool_images.count_documents({'projectId': {'$exists': False}, 'dismissed': {'$ne': True}})
        total_assigned = mongo.db.pool_images.count_documents({'projectId': {'$exists': True}})
        return jsonify({
            'totalUnassigned': total_unassigned,
            'totalAssigned': total_assigned,
            'bySender': [serialize_doc(s) for s in by_sender],
        })
    
    status = request.args.get('status', 'unassigned')
    phone = request.args.get('phone', '')
    project_filter = request.args.get('project', '')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))

    query = {}
    if status == 'unassigned':
        query['projectId'] = {'$exists': False}
        query['dismissed'] = {'$ne': True}
    elif status == 'assigned':
        query['projectId'] = {'$exists': True}
    if phone:
        query['phone'] = phone
    if project_filter:
        query['projectId'] = ObjectId(project_filter)

    total = mongo.db.pool_images.count_documents(query)
    skip = (page - 1) * limit
    images = list(mongo.db.pool_images.find(query).sort('createdAt', -1).skip(skip).limit(limit))
    return jsonify({
        'images': [serialize_doc(img) for img in images],
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'pages': (total + limit - 1) // limit if limit else 1,
        },
    })

@wa_image_pool_bp.route('/assign', methods=['POST'])
@jwt_required()
def assign_images():
    data = request.get_json()
    image_ids = data.get('imageIds', [])
    project_id = data.get('projectId')

    if not image_ids or not project_id:
        return jsonify({'error': 'imageIds and projectId required'}), 400

    project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    if project.get('status') != 'active':
        return jsonify({'error': 'Project must be active to assign images'}), 400

    from app.services.image_pool_service import assign_images_to_project

    proj = dict(project)
    nas_folder = (data.get('nasFolderName') or '').strip()
    nas_bucket = (data.get('nasParentBucket') or '').strip()
    if nas_folder:
        proj['nasFolderName'] = nas_folder
    if nas_bucket:
        proj['nasParentBucket'] = nas_bucket
    group_id = (data.get('groupId') or '').strip() or None
    notify_whatsapp = bool(data.get('notifyWhatsApp'))
    remark = (data.get('remark') or '').strip() or None

    try:
        count = assign_images_to_project(
            image_ids, proj, 'operator', remark=remark, group_id=group_id,
        )
    except ValueError as exc:
        from app.services.loomy_pool_batch import (
            PoolAssignNotClassifyTargetError,
            PoolAssignScopeError,
        )

        if isinstance(exc, PoolAssignScopeError):
            return jsonify({
                'error': str(exc),
                'assigned': 0,
                'code': 'pool_assign_scope',
            }), 400
        if isinstance(exc, PoolAssignNotClassifyTargetError):
            return jsonify({
                'error': str(exc),
                'assigned': 0,
                'code': 'not_classify_target',
            }), 400
        logger.exception('[ImagePool] Manual assign failed')
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        logger.exception('[ImagePool] Manual assign failed')
        return jsonify({'error': str(exc)}), 500

    if count == 0:
        return jsonify({
            'error': 'No files were assigned (they may already be assigned to a project)',
            'assigned': 0,
        }), 409

    return jsonify({
        'assigned': count,
        'projectCode': project['code'],
        'whatsappNotified': False,
        'remark': remark,
        'siteRemarkQueued': bool(remark),
    })

@wa_image_pool_bp.route('/site-remark', methods=['POST'])
@jwt_required()
def append_site_remark():
    """Append a note to Photo/YYYY-MM-DD/<code>_date.txt after photos were filed."""
    data = request.get_json() or {}
    project_code = (data.get('projectCode') or data.get('project_code') or '').strip()
    text = (data.get('text') or data.get('remark') or '').strip()
    if not project_code or not text:
        return jsonify({'error': 'projectCode and text required'}), 400

    from app.services.nas_site_remark_service import (
        append_site_remark_to_nas,
        _merge_remark_into_latest_record,
    )

    nas_folder = (data.get('nasFolderName') or '').strip() or None
    nas_bucket = (data.get('nasParentBucket') or '').strip() or None
    day = (data.get('day') or '').strip() or None
    phone = (data.get('phone') or '').strip() or None
    group_id = (data.get('groupId') or '').strip() or None

    remark_file = (data.get('remarkFilename') or data.get('remark_filename') or '').strip() or None

    result = append_site_remark_to_nas(
        project_code,
        text,
        day_str=day,
        preferred_folder_name=nas_folder,
        preferred_parent_bucket=nas_bucket,
        preferred_remark_filename=remark_file,
    )
    if not result.get('ok'):
        status = 409 if result.get('error') == 'duplicate_remark_txt' else 503
        return jsonify(result), status

    if phone and not result.get('skipped'):
        _merge_remark_into_latest_record(phone, text, project_code, group_id=group_id)

    return jsonify(result)


@wa_image_pool_bp.route('/site-remark/rename', methods=['POST'])
@jwt_required()
def rename_site_remark():
    """Rename the NAS day remark .txt (custom basename allowed; duplicate names in day folder rejected)."""
    data = request.get_json() or {}
    project_code = (data.get('projectCode') or data.get('project_code') or '').strip()
    new_name = (data.get('newFilename') or data.get('new_filename') or '').strip()
    if not project_code or not new_name:
        return jsonify({'error': 'projectCode and newFilename required'}), 400

    from app.services.nas_site_remark_service import (
        rename_site_remark_txt,
        set_site_remark_context,
        hk_today_str,
    )

    nas_folder = (data.get('nasFolderName') or '').strip() or None
    nas_bucket = (data.get('nasParentBucket') or '').strip() or None
    day = (data.get('day') or '').strip() or None
    old_name = (data.get('oldFilename') or data.get('old_filename') or '').strip() or None
    phone = (data.get('phone') or '').strip() or None
    group_id = (data.get('groupId') or '').strip() or None

    result = rename_site_remark_txt(
        project_code,
        new_name,
        day_str=day,
        old_filename=old_name,
        preferred_folder_name=nas_folder,
        preferred_parent_bucket=nas_bucket,
    )
    if not result.get('ok'):
        status = 409 if result.get('error') == 'duplicate_remark_txt' else 400
        return jsonify(result), status

    if phone and result.get('fileName') and not result.get('unchanged'):
        set_site_remark_context(
            phone,
            project_code,
            group_id=group_id,
            day_str=day or hk_today_str(),
            nas_folder_name=nas_folder,
            nas_parent_bucket=nas_bucket,
            remark_file_name=result['fileName'],
        )

    return jsonify(result)


@wa_image_pool_bp.route('/move', methods=['POST'])
@jwt_required()
@require_role('admin', 'manager')
def move_images():
    """Move assigned pool images (or whole record) to another project."""
    data = request.get_json() or {}
    record_ref = (data.get('recordReference') or data.get('recordId') or '').strip()
    image_ids = data.get('imageIds') or data.get('poolImageIds') or []
    target_code = (data.get('targetProjectCode') or data.get('projectCode') or '').strip()
    project_id = (data.get('projectId') or '').strip()
    relocate_nas = data.get('relocateNas', True)
    if isinstance(relocate_nas, str):
        relocate_nas = relocate_nas.strip().lower() not in ('0', 'false', 'no')

    project = None
    if project_id:
        project = mongo.db.wa_projects.find_one({'_id': ObjectId(project_id)})
    elif target_code:
        code = target_code.strip()
        project = mongo.db.wa_projects.find_one({
            'code': {'$regex': f'^{re.escape(code)}$', '$options': 'i'},
            'status': 'active',
        })
    if not project:
        return jsonify({'error': 'Target project not found'}), 404

    proj = dict(project)
    nas_folder = (data.get('nasFolderName') or '').strip()
    nas_bucket = (data.get('nasParentBucket') or '').strip()
    if nas_folder:
        proj['nasFolderName'] = nas_folder
    if nas_bucket:
        proj['nasParentBucket'] = nas_bucket

    from app.services.image_pool_service import move_images_to_project, move_record_to_project

    try:
        if record_ref:
            result = move_record_to_project(
                record_ref,
                proj,
                moved_by='operator',
                relocate_nas=bool(relocate_nas),
            )
        elif image_ids:
            result = move_images_to_project(
                image_ids,
                proj,
                moved_by='operator',
                relocate_nas=bool(relocate_nas),
            )
        else:
            return jsonify({'error': 'recordReference or imageIds required'}), 400
    except Exception as exc:
        logger.exception('[ImagePool] Move failed')
        return jsonify({'error': str(exc)}), 500

    if result.get('moved', 0) <= 0:
        return jsonify({**result, 'error': '; '.join(result.get('errors') or ['move failed'])}), 409

    return jsonify({
        **result,
        'targetProjectCode': proj.get('code'),
    })


@wa_image_pool_bp.route('/retry-download', methods=['POST'])
@jwt_required()
def retry_download():
    data = request.get_json()
    image_ids = data.get('imageIds', [])
    succeeded = 0
    
    for img_id in image_ids:
        img = mongo.db.pool_images.find_one({'_id': ObjectId(img_id)})
        if not img or not img.get('messageId'):
            continue
        
        try:
            from app.services.wa_send_service import download_media
            media_bytes = download_media(img['messageId'])
            if media_bytes:
                import os, hashlib
                from flask import current_app
                ext = '.jpg'
                fname = hashlib.md5(img['messageId'].encode()).hexdigest() + ext
                folder = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')
                os.makedirs(folder, exist_ok=True)
                fpath = os.path.join(folder, fname)
                with open(fpath, 'wb') as f:
                    f.write(media_bytes)
                
                mongo.db.pool_images.update_one(
                    {'_id': ObjectId(img_id)},
                    {'$set': {'imagePath': f'/uploads/wa-media/{fname}', 'downloadFailed': False, 'updatedAt': datetime.utcnow()}}
                )
                succeeded += 1
        except Exception:
            pass
    
    return jsonify({'succeeded': succeeded})

@wa_image_pool_bp.route('/delete', methods=['POST'])
@jwt_required()
def delete_images():
    data = request.get_json()
    image_ids = data.get('imageIds', [])
    oids = [ObjectId(i) for i in image_ids]

    msg_ids = [img['messageId'] for img in
               mongo.db.pool_images.find({'_id': {'$in': oids}}, {'messageId': 1})
               if img.get('messageId')]

    r1 = mongo.db.pool_images.delete_many({'_id': {'$in': oids}})

    if msg_ids:
        mongo.db.group_pending_images.delete_many({
            'messageId': {'$in': msg_ids},
            'categorized': False,
        })

    return jsonify({'deleted': r1.deleted_count})
