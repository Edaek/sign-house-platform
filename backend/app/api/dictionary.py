"""Dictionary API endpoints for managing English-Chinese translation pairs."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime

from app import mongo
from app.models import create_dictionary_entry_doc, dictionary_entry_to_dict, serialize_doc
from app.services.audit_service import log_action

dictionary_bp = Blueprint('dictionary', __name__)


@dictionary_bp.route('', methods=['GET'])
@jwt_required()
def list_entries():
    """List all dictionary entries with search and pagination."""
    try:
        # Get query parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        search = request.args.get('search', '').strip()
        
        # Build query
        query = {}
        if search:
            query['$or'] = [
                {'english': {'$regex': search, '$options': 'i'}},
                {'chinese': {'$regex': search, '$options': 'i'}}
            ]
        
        # Get total count
        total = mongo.db.dictionary.count_documents(query)
        
        # Calculate pagination
        skip = (page - 1) * per_page
        total_pages = max(1, (total + per_page - 1) // per_page)
        
        # Get entries with pagination
        entries_cursor = mongo.db.dictionary.find(query).sort('english', 1).skip(skip).limit(per_page)
        
        entries = [dictionary_entry_to_dict(entry) for entry in entries_cursor]
        
        return jsonify({
            'entries': entries,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('', methods=['POST'])
@jwt_required()
def create_entry():
    """Create a new dictionary entry."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        english = data.get('english', '').strip()
        chinese = data.get('chinese', '').strip()
        
        if not english and not chinese:
            return jsonify({'error': 'At least one of English or Chinese is required'}), 400
        
        # Check for duplicates
        existing = mongo.db.dictionary.find_one({
            '$or': [
                {'english': english} if english else {'_id': None},
                {'chinese': chinese} if chinese else {'_id': None}
            ]
        })
        
        if existing:
            return jsonify({'error': 'An entry with this English or Chinese value already exists'}), 409
        
        # Create entry
        entry_doc = create_dictionary_entry_doc(english, chinese, user_id)
        result = mongo.db.dictionary.insert_one(entry_doc)
        entry_doc['_id'] = result.inserted_id
        
        # Log action
        log_action(
            user_id=user_id,
            action='dictionary_entry_created',
            resource_type='dictionary',
            resource_id=str(result.inserted_id),
            details={'english': english, 'chinese': chinese}
        )
        
        return jsonify({
            'message': 'Dictionary entry created successfully',
            'entry': dictionary_entry_to_dict(entry_doc)
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/<entry_id>', methods=['GET'])
@jwt_required()
def get_entry(entry_id):
    """Get a specific dictionary entry."""
    try:
        entry = mongo.db.dictionary.find_one({'_id': ObjectId(entry_id)})
        
        if not entry:
            return jsonify({'error': 'Dictionary entry not found'}), 404
        
        return jsonify({'entry': dictionary_entry_to_dict(entry)}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/<entry_id>', methods=['PUT'])
@jwt_required()
def update_entry(entry_id):
    """Update a dictionary entry."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        entry = mongo.db.dictionary.find_one({'_id': ObjectId(entry_id)})
        
        if not entry:
            return jsonify({'error': 'Dictionary entry not found'}), 404
        
        english = data.get('english', '').strip()
        chinese = data.get('chinese', '').strip()
        
        if not english and not chinese:
            return jsonify({'error': 'At least one of English or Chinese is required'}), 400
        
        # Check for duplicates (excluding current entry)
        existing = mongo.db.dictionary.find_one({
            '_id': {'$ne': ObjectId(entry_id)},
            '$or': [
                {'english': english} if english else {'_id': None},
                {'chinese': chinese} if chinese else {'_id': None}
            ]
        })
        
        if existing:
            return jsonify({'error': 'Another entry with this English or Chinese value already exists'}), 409
        
        # Update entry
        mongo.db.dictionary.update_one(
            {'_id': ObjectId(entry_id)},
            {
                '$set': {
                    'english': english,
                    'chinese': chinese,
                    'updated_at': datetime.utcnow()
                }
            }
        )
        
        # Log action
        log_action(
            user_id=user_id,
            action='dictionary_entry_updated',
            resource_type='dictionary',
            resource_id=entry_id,
            details={
                'old_english': entry.get('english'),
                'old_chinese': entry.get('chinese'),
                'new_english': english,
                'new_chinese': chinese
            }
        )
        
        updated_entry = mongo.db.dictionary.find_one({'_id': ObjectId(entry_id)})
        
        return jsonify({
            'message': 'Dictionary entry updated successfully',
            'entry': dictionary_entry_to_dict(updated_entry)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/<entry_id>', methods=['DELETE'])
@jwt_required()
def delete_entry(entry_id):
    """Delete a dictionary entry."""
    try:
        user_id = get_jwt_identity()
        
        entry = mongo.db.dictionary.find_one({'_id': ObjectId(entry_id)})
        
        if not entry:
            return jsonify({'error': 'Dictionary entry not found'}), 404
        
        mongo.db.dictionary.delete_one({'_id': ObjectId(entry_id)})
        
        # Log action
        log_action(
            user_id=user_id,
            action='dictionary_entry_deleted',
            resource_type='dictionary',
            resource_id=entry_id,
            details={
                'english': entry.get('english'),
                'chinese': entry.get('chinese')
            }
        )
        
        return jsonify({'message': 'Dictionary entry deleted successfully'}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/bulk', methods=['POST'])
@jwt_required()
def bulk_import():
    """Bulk import dictionary entries from a list."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        if not data or 'entries' not in data:
            return jsonify({'error': 'Entries list is required'}), 400
        
        entries = data['entries']
        
        if not isinstance(entries, list):
            return jsonify({'error': 'Entries must be a list'}), 400
        
        if len(entries) == 0:
            return jsonify({'error': 'Entries list is empty'}), 400
        
        if len(entries) > 1000:
            return jsonify({'error': 'Maximum 1000 entries per import'}), 400
        
        created_count = 0
        skipped_count = 0
        errors = []
        
        for idx, entry_data in enumerate(entries):
            english = entry_data.get('english', '').strip() if entry_data.get('english') else ''
            chinese = entry_data.get('chinese', '').strip() if entry_data.get('chinese') else ''
            
            if not english and not chinese:
                errors.append(f'Row {idx + 1}: At least one value required')
                skipped_count += 1
                continue
            
            # Check for duplicates
            existing_query = []
            if english:
                existing_query.append({'english': english})
            if chinese:
                existing_query.append({'chinese': chinese})
            
            existing = mongo.db.dictionary.find_one({'$or': existing_query}) if existing_query else None
            
            if existing:
                skipped_count += 1
                continue
            
            # Create entry
            entry_doc = create_dictionary_entry_doc(english, chinese, user_id)
            mongo.db.dictionary.insert_one(entry_doc)
            created_count += 1
        
        # Log action
        log_action(
            user_id=user_id,
            action='dictionary_bulk_import',
            resource_type='dictionary',
            details={
                'total_entries': len(entries),
                'created': created_count,
                'skipped': skipped_count
            }
        )
        
        return jsonify({
            'message': f'Bulk import completed',
            'created': created_count,
            'skipped': skipped_count,
            'errors': errors[:10]  # Return first 10 errors only
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/lookup', methods=['GET'])
@jwt_required()
def lookup():
    """Look up a translation. Provide either 'english' or 'chinese' query param."""
    try:
        english = request.args.get('english', '').strip()
        chinese = request.args.get('chinese', '').strip()
        
        if not english and not chinese:
            return jsonify({'error': 'Provide either english or chinese parameter'}), 400
        
        if english:
            entry = mongo.db.dictionary.find_one({'english': {'$regex': f'^{english}$', '$options': 'i'}})
            if entry:
                return jsonify({
                    'found': True,
                    'english': entry.get('english'),
                    'chinese': entry.get('chinese')
                }), 200
        
        if chinese:
            entry = mongo.db.dictionary.find_one({'chinese': chinese})
            if entry:
                return jsonify({
                    'found': True,
                    'english': entry.get('english'),
                    'chinese': entry.get('chinese')
                }), 200
        
        return jsonify({'found': False}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_stats():
    """Get dictionary statistics."""
    try:
        total = mongo.db.dictionary.count_documents({})
        with_both = mongo.db.dictionary.count_documents({
            'english': {'$ne': ''},
            'chinese': {'$ne': ''}
        })
        english_only = mongo.db.dictionary.count_documents({
            'english': {'$ne': ''},
            'chinese': ''
        })
        chinese_only = mongo.db.dictionary.count_documents({
            'english': '',
            'chinese': {'$ne': ''}
        })
        
        return jsonify({
            'total': total,
            'with_both': with_both,
            'english_only': english_only,
            'chinese_only': chinese_only
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/fill-template/<project_id>', methods=['POST'])
@jwt_required()
def fill_template_gaps(project_id):
    """
    Fill missing English or Chinese values in a project's template using dictionary lookups.
    
    Request body:
    {
        "english_column": "English Name",  # Name of the English column
        "chinese_column": "Chinese Name"   # Name of the Chinese column
    }
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        english_col_name = data.get('english_column', '').strip()
        chinese_col_name = data.get('chinese_column', '').strip()
        
        if not english_col_name or not chinese_col_name:
            return jsonify({'error': 'Both english_column and chinese_column are required'}), 400
        
        # Get the project's template
        template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
        
        if not template:
            return jsonify({'error': 'No template found for this project'}), 404
        
        template_path = template.get('filepath')
        
        if not template_path:
            return jsonify({'error': 'Template file path not found'}), 404
        
        # Import and use the dictionary service
        from app.services.dictionary_service import fill_template_file_gaps
        
        stats = fill_template_file_gaps(template_path, english_col_name, chinese_col_name)
        
        if 'error' in stats:
            return jsonify({'error': stats['error']}), 400
        
        # Log action
        log_action(
            user_id=user_id,
            action='template_dictionary_fill',
            resource_type='project',
            resource_id=project_id,
            details={
                'english_column': english_col_name,
                'chinese_column': chinese_col_name,
                'english_filled': stats.get('english_filled', 0),
                'chinese_filled': stats.get('chinese_filled', 0),
                'not_found': stats.get('not_found', 0)
            }
        )
        
        return jsonify({
            'message': 'Template gaps filled successfully',
            'stats': stats
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/export', methods=['GET'])
@jwt_required()
def export_dictionary():
    """Export all dictionary entries as JSON."""
    try:
        entries = list(mongo.db.dictionary.find({}).sort('english', 1))
        
        export_data = []
        for entry in entries:
            export_data.append({
                'english': entry.get('english', ''),
                'chinese': entry.get('chinese', '')
            })
        
        return jsonify({
            'entries': export_data,
            'total': len(export_data)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

