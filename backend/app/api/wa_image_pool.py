import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from bson import ObjectId
from datetime import datetime
from app import mongo
from app.models import serialize_doc

logger = logging.getLogger(__name__)
wa_image_pool_bp = Blueprint('wa_image_pool', __name__)

@wa_image_pool_bp.route('', methods=['GET'])
@jwt_required()
def list_or_stats():
    mode = request.args.get('mode')
    if mode == 'stats':
        pipeline = [
            {'$match': {'projectId': {'$exists': False}}},
            {'$group': {'_id': '$phone', 'count': {'$sum': 1},
                       'senderName': {'$first': '$senderName'},
                       'latestAt': {'$max': '$createdAt'}}},
            {'$sort': {'latestAt': -1}}
        ]
        by_sender = list(mongo.db.pool_images.aggregate(pipeline))
        total_unassigned = mongo.db.pool_images.count_documents({'projectId': {'$exists': False}})
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
    try:
        count = assign_images_to_project(image_ids, project, 'operator')
    except Exception as exc:
        logger.exception('[ImagePool] Manual assign failed')
        return jsonify({'error': str(exc)}), 500

    if count == 0:
        return jsonify({
            'error': 'No files were assigned (they may already be assigned to a project)',
            'assigned': 0,
        }), 409
    return jsonify({'assigned': count, 'projectCode': project['code']})

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
