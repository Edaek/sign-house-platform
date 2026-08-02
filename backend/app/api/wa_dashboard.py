from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from datetime import datetime, timedelta
from app import mongo

wa_dashboard_bp = Blueprint('wa_dashboard', __name__)

@wa_dashboard_bp.route('/dashboard/stats', methods=['GET'])
@jwt_required()
def dashboard_stats():
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    overdue_cutoff = now - timedelta(hours=24)
    count = lambda match: mongo.db.wa_records.count_documents(match)

    stats = {
        'todayIntake': count({'createdAt': {'$gte': today}}),
        'pendingCompletion': count({'status': {'$in': ['incomplete', 'followup']}}),
        'awaitingReview': count({'status': 'awaiting_review'}),
        'completedToday': count({'status': 'completed', 'updatedAt': {'$gte': today}}),
        'followUpOverdue': count({
            'status': 'followup',
            'lastFollowUpAt': {'$lt': overdue_cutoff},
        }),
    }
    return jsonify(stats)

@wa_dashboard_bp.route('/dashboard/recent', methods=['GET'])
@jwt_required()
def dashboard_recent():
    records = list(mongo.db.wa_records.find({}, {
        'referenceNumber': 1, 'status': 1, 'type': 1,
        'senderPhone': 1, 'senderName': 1, 'createdAt': 1
    }).sort('createdAt', -1).limit(8))
    
    from app.models import serialize_doc
    return jsonify({'records': [serialize_doc(r) for r in records]})

@wa_dashboard_bp.route('/search', methods=['GET'])
@jwt_required()
def search_records():
    q = request.args.get('q', '')
    status = request.args.get('status', '')
    phone = request.args.get('phone', '')
    project = request.args.get('project', '')
    from_date = request.args.get('from', '')
    to_date = request.args.get('to', '')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))

    query = {}
    if q:
        query['$or'] = [
            {'referenceNumber': {'$regex': q, '$options': 'i'}},
            {'senderPhone': {'$regex': q, '$options': 'i'}},
            {'senderName': {'$regex': q, '$options': 'i'}},
            {'rawMessage': {'$regex': q, '$options': 'i'}},
        ]
    if status:
        query['status'] = {'$in': status.split(',')}
    if phone:
        query['senderPhone'] = {'$regex': phone, '$options': 'i'}
    if project:
        from bson import ObjectId as _OID
        try:
            query['projectId'] = _OID(project)
        except Exception:
            pass
    if from_date or to_date:
        date_q = {}
        if from_date:
            date_q['$gte'] = datetime.fromisoformat(from_date)
        if to_date:
            date_q['$lte'] = datetime.fromisoformat(to_date)
        if date_q:
            query['createdAt'] = date_q

    total = mongo.db.wa_records.count_documents(query)
    skip = (page - 1) * limit
    records = list(mongo.db.wa_records.find(query).sort('createdAt', -1).skip(skip).limit(limit))
    from app.models import serialize_doc
    return jsonify({
        'records': [serialize_doc(r) for r in records],
        'pagination': {
            'page': page,
            'limit': limit,
            'total': total,
            'pages': (total + limit - 1) // limit if limit else 1,
        },
    })
