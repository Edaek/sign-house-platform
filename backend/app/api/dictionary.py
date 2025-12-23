"""Dictionary API endpoints for managing English-Chinese translation pairs.

This is an English-first dictionary where each English word can have multiple
Chinese translations stored as an array.
"""
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
        
        # Build query - search in english or any chinese translation
        query = {}
        if search:
            query['$or'] = [
                {'english': {'$regex': search, '$options': 'i'}},
                {'chinese': {'$elemMatch': {'$regex': search, '$options': 'i'}}}
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
    """Create a new dictionary entry.
    
    Request body:
    {
        "english": "Exit",
        "sign": "EXIT-001",  # Optional sign name/code
        "chinese": ["出口", "退出"]  # Can be array or single string
    }
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        english = data.get('english', '').strip() if data.get('english') else ''
        sign = data.get('sign', '').strip() if data.get('sign') else ''
        chinese = data.get('chinese', [])
        
        # Normalize chinese to list
        if isinstance(chinese, str):
            chinese = [chinese.strip()] if chinese.strip() else []
        elif isinstance(chinese, list):
            chinese = [c.strip() for c in chinese if c and str(c).strip()]
        else:
            chinese = []
        
        if not english:
            return jsonify({'error': 'English word is required'}), 400
        
        # Check if English word already exists (English is the unique key)
        existing = mongo.db.dictionary.find_one({'english': {'$regex': f'^{english}$', '$options': 'i'}})
        
        if existing:
            return jsonify({'error': f'An entry for "{english}" already exists'}), 409
        
        # Create entry
        entry_doc = create_dictionary_entry_doc(english, chinese, user_id, sign)
        result = mongo.db.dictionary.insert_one(entry_doc)
        entry_doc['_id'] = result.inserted_id
        
        # Log action
        log_action(
            user_id=user_id,
            action='dictionary_entry_created',
            resource_type='dictionary',
            resource_id=str(result.inserted_id),
            details={'english': english, 'sign': sign, 'chinese': chinese}
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
    """Update a dictionary entry.
    
    Request body:
    {
        "english": "Exit",
        "sign": "EXIT-001",
        "chinese": ["出口", "退出"]
    }
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        entry = mongo.db.dictionary.find_one({'_id': ObjectId(entry_id)})
        
        if not entry:
            return jsonify({'error': 'Dictionary entry not found'}), 404
        
        english = data.get('english', '').strip() if data.get('english') else ''
        sign = data.get('sign', '').strip() if data.get('sign') else ''
        chinese = data.get('chinese', [])
        
        # Normalize chinese to list
        if isinstance(chinese, str):
            chinese = [chinese.strip()] if chinese.strip() else []
        elif isinstance(chinese, list):
            chinese = [c.strip() for c in chinese if c and str(c).strip()]
        else:
            chinese = []
        
        if not english:
            return jsonify({'error': 'English word is required'}), 400
        
        # Check for duplicate English (excluding current entry)
        existing = mongo.db.dictionary.find_one({
            '_id': {'$ne': ObjectId(entry_id)},
            'english': {'$regex': f'^{english}$', '$options': 'i'}
        })
        
        if existing:
            return jsonify({'error': f'Another entry for "{english}" already exists'}), 409
        
        # Update entry
        mongo.db.dictionary.update_one(
            {'_id': ObjectId(entry_id)},
            {
                '$set': {
                    'english': english,
                    'sign': sign,
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
                'old_sign': entry.get('sign'),
                'old_chinese': entry.get('chinese'),
                'new_english': english,
                'new_sign': sign,
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


@dictionary_bp.route('/<entry_id>/chinese', methods=['POST'])
@jwt_required()
def add_chinese_translation(entry_id):
    """Add a Chinese translation to an existing entry.
    
    Request body:
    {
        "chinese": "新翻译"
    }
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        if not data or not data.get('chinese'):
            return jsonify({'error': 'Chinese translation is required'}), 400
        
        entry = mongo.db.dictionary.find_one({'_id': ObjectId(entry_id)})
        
        if not entry:
            return jsonify({'error': 'Dictionary entry not found'}), 404
        
        new_chinese = data.get('chinese', '').strip()
        
        if not new_chinese:
            return jsonify({'error': 'Chinese translation is required'}), 400
        
        # Get current chinese list
        current_chinese = entry.get('chinese', [])
        if isinstance(current_chinese, str):
            current_chinese = [current_chinese] if current_chinese else []
        
        # Check if translation already exists
        if new_chinese in current_chinese:
            return jsonify({'error': 'This translation already exists'}), 409
        
        # Add the new translation
        mongo.db.dictionary.update_one(
            {'_id': ObjectId(entry_id)},
            {
                '$push': {'chinese': new_chinese},
                '$set': {'updated_at': datetime.utcnow()}
            }
        )
        
        # Log action
        log_action(
            user_id=user_id,
            action='dictionary_chinese_added',
            resource_type='dictionary',
            resource_id=entry_id,
            details={
                'english': entry.get('english'),
                'added_chinese': new_chinese
            }
        )
        
        updated_entry = mongo.db.dictionary.find_one({'_id': ObjectId(entry_id)})
        
        return jsonify({
            'message': 'Chinese translation added successfully',
            'entry': dictionary_entry_to_dict(updated_entry)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/<entry_id>/chinese/<int:index>', methods=['DELETE'])
@jwt_required()
def remove_chinese_translation(entry_id, index):
    """Remove a Chinese translation by index from an entry."""
    try:
        user_id = get_jwt_identity()
        
        entry = mongo.db.dictionary.find_one({'_id': ObjectId(entry_id)})
        
        if not entry:
            return jsonify({'error': 'Dictionary entry not found'}), 404
        
        current_chinese = entry.get('chinese', [])
        if isinstance(current_chinese, str):
            current_chinese = [current_chinese] if current_chinese else []
        
        if index < 0 or index >= len(current_chinese):
            return jsonify({'error': 'Invalid translation index'}), 400
        
        removed_chinese = current_chinese[index]
        current_chinese.pop(index)
        
        # Update entry
        mongo.db.dictionary.update_one(
            {'_id': ObjectId(entry_id)},
            {
                '$set': {
                    'chinese': current_chinese,
                    'updated_at': datetime.utcnow()
                }
            }
        )
        
        # Log action
        log_action(
            user_id=user_id,
            action='dictionary_chinese_removed',
            resource_type='dictionary',
            resource_id=entry_id,
            details={
                'english': entry.get('english'),
                'removed_chinese': removed_chinese
            }
        )
        
        updated_entry = mongo.db.dictionary.find_one({'_id': ObjectId(entry_id)})
        
        return jsonify({
            'message': 'Chinese translation removed successfully',
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


@dictionary_bp.route('/add-translation', methods=['POST'])
@jwt_required()
def add_translation():
    """Add a translation to the dictionary.
    
    If the English word doesn't exist, creates a new entry.
    If it exists, adds the Chinese translation to the existing entry.
    
    Request body:
    {
        "english": "Exit",
        "chinese": "出口"
    }
    
    Response:
    {
        "action": "created" | "added" | "exists",
        "entry": {...}
    }
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        english = data.get('english', '').strip() if data.get('english') else ''
        chinese = data.get('chinese', '').strip() if data.get('chinese') else ''
        
        if not english:
            return jsonify({'error': 'English word is required'}), 400
        
        if not chinese:
            return jsonify({'error': 'Chinese translation is required'}), 400
        
        # Check if English word already exists
        existing = mongo.db.dictionary.find_one({'english': {'$regex': f'^{english}$', '$options': 'i'}})
        
        if existing:
            # Check if this Chinese translation already exists
            current_chinese = existing.get('chinese', [])
            if isinstance(current_chinese, str):
                current_chinese = [current_chinese] if current_chinese else []
            
            if chinese in current_chinese:
                # Translation already exists
                return jsonify({
                    'action': 'exists',
                    'message': 'Translation already exists in dictionary',
                    'entry': dictionary_entry_to_dict(existing)
                }), 200
            
            # Add the new translation
            mongo.db.dictionary.update_one(
                {'_id': existing['_id']},
                {
                    '$push': {'chinese': chinese},
                    '$set': {'updated_at': datetime.utcnow()}
                }
            )
            
            # Log action
            log_action(
                user_id=user_id,
                action='dictionary_translation_added',
                resource_type='dictionary',
                resource_id=str(existing['_id']),
                details={'english': english, 'added_chinese': chinese}
            )
            
            updated_entry = mongo.db.dictionary.find_one({'_id': existing['_id']})
            
            return jsonify({
                'action': 'added',
                'message': f'Added translation to existing entry',
                'entry': dictionary_entry_to_dict(updated_entry)
            }), 200
        else:
            # Create new entry
            entry_doc = create_dictionary_entry_doc(english, [chinese], user_id)
            result = mongo.db.dictionary.insert_one(entry_doc)
            entry_doc['_id'] = result.inserted_id
            
            # Log action
            log_action(
                user_id=user_id,
                action='dictionary_entry_created',
                resource_type='dictionary',
                resource_id=str(result.inserted_id),
                details={'english': english, 'chinese': [chinese]}
            )
            
            return jsonify({
                'action': 'created',
                'message': 'Created new dictionary entry',
                'entry': dictionary_entry_to_dict(entry_doc)
            }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/bulk', methods=['POST'])
@jwt_required()
def bulk_import():
    """Bulk import dictionary entries from a list.
    
    Request body:
    {
        "entries": [
            {"english": "Exit", "sign": "EXIT-001", "chinese": ["出口", "退出"]},
            {"english": "Fire", "sign": "FIRE-001", "chinese": "火"}
        ]
    }
    
    Format: Each entry has english (required), sign (optional), and chinese (array or string).
    If an English word already exists, the Chinese translations are merged and sign is updated.
    """
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
        updated_count = 0
        skipped_count = 0
        errors = []
        
        for idx, entry_data in enumerate(entries):
            english = entry_data.get('english', '').strip() if entry_data.get('english') else ''
            sign = entry_data.get('sign', '').strip() if entry_data.get('sign') else ''
            chinese = entry_data.get('chinese', [])
            
            # Normalize chinese to list
            if isinstance(chinese, str):
                chinese = [chinese.strip()] if chinese.strip() else []
            elif isinstance(chinese, list):
                chinese = [str(c).strip() for c in chinese if c and str(c).strip()]
            else:
                chinese = []
            
            if not english:
                errors.append(f'Row {idx + 1}: English word is required')
                skipped_count += 1
                continue
            
            # Check if English word already exists
            existing = mongo.db.dictionary.find_one({'english': {'$regex': f'^{english}$', '$options': 'i'}})
            
            if existing:
                # Merge Chinese translations
                current_chinese = existing.get('chinese', [])
                if isinstance(current_chinese, str):
                    current_chinese = [current_chinese] if current_chinese else []
                
                # Add new translations that don't exist
                new_translations = [c for c in chinese if c not in current_chinese]
                
                # Build update operations
                update_ops = {'$set': {'updated_at': datetime.utcnow()}}
                
                if new_translations:
                    update_ops['$push'] = {'chinese': {'$each': new_translations}}
                
                # Update sign if provided and different
                if sign and sign != existing.get('sign', ''):
                    update_ops['$set']['sign'] = sign
                
                if new_translations or (sign and sign != existing.get('sign', '')):
                    mongo.db.dictionary.update_one(
                        {'_id': existing['_id']},
                        update_ops
                    )
                    updated_count += 1
                else:
                    skipped_count += 1
            else:
                # Create new entry
                entry_doc = create_dictionary_entry_doc(english, chinese, user_id, sign)
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
                'updated': updated_count,
                'skipped': skipped_count
            }
        )
        
        return jsonify({
            'message': 'Bulk import completed',
            'created': created_count,
            'updated': updated_count,
            'skipped': skipped_count,
            'errors': errors[:10]  # Return first 10 errors only
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/search', methods=['GET'])
@jwt_required()
def search():
    """Instant search for autocomplete.
    
    Query params:
    - q: Search query (searches in English words)
    - limit: Maximum results to return (default 10, max 50)
    
    Returns matching English words with their sign and Chinese translations.
    Prioritizes exact prefix matches, then contains matches.
    """
    try:
        query = request.args.get('q', '').strip()
        limit = min(int(request.args.get('limit', 10)), 50)
        
        if not query:
            return jsonify({'results': []}), 200
        
        if len(query) < 1:
            return jsonify({'results': []}), 200
        
        # Search for English words matching the query
        # Use case-insensitive regex search
        # First try prefix match, then contains match
        
        results = []
        seen_english = set()
        
        # Prefix matches first (higher priority)
        prefix_pattern = f'^{query}'
        prefix_entries = mongo.db.dictionary.find({
            'english': {'$regex': prefix_pattern, '$options': 'i'}
        }).sort('english', 1).limit(limit)
        
        for entry in prefix_entries:
            english = entry.get('english', '')
            if english.lower() not in seen_english:
                seen_english.add(english.lower())
                sign = entry.get('sign', '')
                chinese = entry.get('chinese', [])
                if isinstance(chinese, str):
                    chinese = [chinese] if chinese else []
                results.append({
                    'english': english,
                    'sign': sign,
                    'chinese': chinese,
                    'match_type': 'prefix'
                })
        
        # If we haven't reached the limit, add contains matches
        if len(results) < limit:
            remaining = limit - len(results)
            contains_pattern = query
            contains_entries = mongo.db.dictionary.find({
                'english': {'$regex': contains_pattern, '$options': 'i'}
            }).sort('english', 1).limit(remaining + len(results))  # Get extra to filter duplicates
            
            for entry in contains_entries:
                if len(results) >= limit:
                    break
                english = entry.get('english', '')
                if english.lower() not in seen_english:
                    seen_english.add(english.lower())
                    sign = entry.get('sign', '')
                    chinese = entry.get('chinese', [])
                    if isinstance(chinese, str):
                        chinese = [chinese] if chinese else []
                    results.append({
                        'english': english,
                        'sign': sign,
                        'chinese': chinese,
                        'match_type': 'contains'
                    })
        
        return jsonify({
            'results': results[:limit],
            'query': query,
            'count': len(results[:limit])
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/lookup', methods=['GET'])
@jwt_required()
def lookup():
    """Look up a translation.
    
    Query params:
    - english: Look up sign and Chinese translations for an English word
    - chinese: Look up English word(s) for a Chinese term
    
    When looking up by Chinese, returns all matching English words (for dropdown selection).
    """
    try:
        english = request.args.get('english', '').strip()
        chinese = request.args.get('chinese', '').strip()
        
        if not english and not chinese:
            return jsonify({'error': 'Provide either english or chinese parameter'}), 400
        
        if english:
            # Look up sign and Chinese translations for English word
            entry = mongo.db.dictionary.find_one({'english': {'$regex': f'^{english}$', '$options': 'i'}})
            if entry:
                chinese_list = entry.get('chinese', [])
                if isinstance(chinese_list, str):
                    chinese_list = [chinese_list] if chinese_list else []
                return jsonify({
                    'found': True,
                    'english': entry.get('english'),
                    'sign': entry.get('sign', ''),
                    'chinese': chinese_list
                }), 200
        
        if chinese:
            # Look up all English words that have this Chinese translation
            entries = list(mongo.db.dictionary.find({'chinese': chinese}))
            
            if entries:
                # Return all matches with the first one as the primary
                matches = [
                    {
                        'english': e.get('english'),
                        'sign': e.get('sign', ''),
                        'chinese': e.get('chinese', []) if isinstance(e.get('chinese'), list) else [e.get('chinese', '')]
                    }
                    for e in entries
                ]
                return jsonify({
                    'found': True,
                    'primary': matches[0]['english'],  # First match is the default
                    'primary_sign': matches[0]['sign'],  # Sign of the primary match
                    'matches': matches,
                    'chinese': chinese
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
        
        # Count entries with at least one Chinese translation
        with_chinese = mongo.db.dictionary.count_documents({
            'chinese': {'$exists': True, '$ne': [], '$type': 'array'}
        })
        
        # Count entries with empty chinese array
        no_chinese = mongo.db.dictionary.count_documents({
            '$or': [
                {'chinese': {'$exists': False}},
                {'chinese': []},
                {'chinese': ''}
            ]
        })
        
        # Count total Chinese translations
        pipeline = [
            {'$project': {'chinese_count': {'$size': {'$ifNull': ['$chinese', []]}}}},
            {'$group': {'_id': None, 'total': {'$sum': '$chinese_count'}}}
        ]
        result = list(mongo.db.dictionary.aggregate(pipeline))
        total_translations = result[0]['total'] if result else 0
        
        return jsonify({
            'total': total,
            'with_chinese': with_chinese,
            'no_chinese': no_chinese,
            'total_translations': total_translations
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
    """Export all dictionary entries as CSV.
    
    CSV format: English,Sign,Chinese (Chinese translations joined with semicolon)
    """
    try:
        import csv
        import io
        from flask import Response
        
        entries = list(mongo.db.dictionary.find({}).sort('english', 1))
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['English', 'Sign', 'Chinese'])
        
        # Write data rows
        for entry in entries:
            english = entry.get('english', '')
            sign = entry.get('sign', '')
            chinese = entry.get('chinese', [])
            if isinstance(chinese, str):
                chinese = [chinese] if chinese else []
            # Join Chinese translations with semicolon
            chinese_str = ';'.join(chinese)
            writer.writerow([english, sign, chinese_str])
        
        # Create response with CSV content
        csv_content = output.getvalue()
        output.close()
        
        return Response(
            csv_content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': 'attachment; filename=dictionary-export.csv',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/import-csv', methods=['POST'])
@jwt_required()
def import_csv():
    """Import dictionary entries from CSV file.
    
    Expected CSV format:
    English,Sign,Chinese1,Chinese2,Chinese3,...
    
    Or with semicolon-separated Chinese:
    English,Sign,Chinese
    Exit,EXIT-001,出口;退出
    
    If an English word already exists, Chinese translations are merged and sign is updated.
    """
    try:
        import csv
        import io
        
        user_id = get_jwt_identity()
        
        # Check if file was uploaded
        if 'file' not in request.files:
            # Try to get CSV data from request body
            csv_data = request.get_data(as_text=True)
            if not csv_data:
                return jsonify({'error': 'No CSV file or data provided'}), 400
        else:
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No file selected'}), 400
            csv_data = file.read().decode('utf-8')
        
        # Parse CSV
        reader = csv.reader(io.StringIO(csv_data))
        rows = list(reader)
        
        if len(rows) < 2:
            return jsonify({'error': 'CSV must have a header row and at least one data row'}), 400
        
        # Skip header row
        header = rows[0]
        data_rows = rows[1:]
        
        if len(data_rows) > 1000:
            return jsonify({'error': 'Maximum 1000 entries per import'}), 400
        
        created_count = 0
        updated_count = 0
        skipped_count = 0
        errors = []
        
        for idx, row in enumerate(data_rows):
            if len(row) < 1:
                skipped_count += 1
                continue
            
            english = row[0].strip() if row[0] else ''
            sign = row[1].strip() if len(row) > 1 and row[1] else ''
            
            # Collect Chinese translations from remaining columns
            chinese = []
            if len(row) > 2:
                # Check if third column contains semicolon-separated values
                third_col = row[2].strip() if row[2] else ''
                if ';' in third_col:
                    # Semicolon-separated format
                    chinese = [c.strip() for c in third_col.split(';') if c.strip()]
                else:
                    # Multiple columns format
                    for i in range(2, len(row)):
                        val = row[i].strip() if row[i] else ''
                        if val:
                            chinese.append(val)
            
            if not english:
                errors.append(f'Row {idx + 2}: English word is required')
                skipped_count += 1
                continue
            
            # Check if English word already exists
            existing = mongo.db.dictionary.find_one({'english': {'$regex': f'^{english}$', '$options': 'i'}})
            
            if existing:
                # Merge Chinese translations
                current_chinese = existing.get('chinese', [])
                if isinstance(current_chinese, str):
                    current_chinese = [current_chinese] if current_chinese else []
                
                # Add new translations that don't exist
                new_translations = [c for c in chinese if c not in current_chinese]
                
                # Build update operations
                update_ops = {'$set': {'updated_at': datetime.utcnow()}}
                
                if new_translations:
                    update_ops['$push'] = {'chinese': {'$each': new_translations}}
                
                # Update sign if provided and different
                if sign and sign != existing.get('sign', ''):
                    update_ops['$set']['sign'] = sign
                
                if new_translations or (sign and sign != existing.get('sign', '')):
                    mongo.db.dictionary.update_one(
                        {'_id': existing['_id']},
                        update_ops
                    )
                    updated_count += 1
                else:
                    skipped_count += 1
            else:
                # Create new entry
                entry_doc = create_dictionary_entry_doc(english, chinese, user_id, sign)
                mongo.db.dictionary.insert_one(entry_doc)
                created_count += 1
        
        # Log action
        log_action(
            user_id=user_id,
            action='dictionary_csv_import',
            resource_type='dictionary',
            details={
                'total_rows': len(data_rows),
                'created': created_count,
                'updated': updated_count,
                'skipped': skipped_count
            }
        )
        
        return jsonify({
            'message': 'CSV import completed',
            'created': created_count,
            'updated': updated_count,
            'skipped': skipped_count,
            'errors': errors[:10]
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/scan-template/<project_id>', methods=['POST'])
@jwt_required()
def scan_template_for_fill(project_id):
    """
    Scan a project's template for cells that need dictionary filling.
    Returns cells with missing values and all possible translation matches.
    
    Request body:
    {
        "english_column": "English Name",
        "chinese_column": "Chinese Name"
    }
    
    Returns:
    {
        "cells_to_fill": [
            {
                "row": 2,
                "english_col": 1,
                "chinese_col": 2,
                "has_english": true,
                "has_chinese": false,
                "english_value": "Exit",
                "chinese_value": "",
                "matches": ["出口", "退出"],  # Chinese translations
                "selected": "出口"  # First match as default
            }
        ],
        "total_to_fill": 5,
        "can_auto_fill": 3  # Cells with only one match
    }
    """
    try:
        import os
        from openpyxl import load_workbook
        
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
        
        if not template_path or not os.path.exists(template_path):
            return jsonify({'error': 'Template file not found'}), 404
        
        workbook = load_workbook(template_path)
        sheet = workbook.active
        
        # Find column indices from header row
        english_col_idx = None
        chinese_col_idx = None
        
        for cell in sheet[1]:
            if cell.value:
                col_name = ' '.join(str(cell.value).split())
                if col_name == english_col_name:
                    english_col_idx = cell.column
                elif col_name == chinese_col_name:
                    chinese_col_idx = cell.column
        
        workbook.close()
        
        if english_col_idx is None or chinese_col_idx is None:
            return jsonify({
                'error': f'Columns not found. Looking for "{english_col_name}" and "{chinese_col_name}"'
            }), 400
        
        # Re-open to scan cells
        workbook = load_workbook(template_path)
        sheet = workbook.active
        
        cells_to_fill = []
        
        # Import service functions
        from app.services.dictionary_service import lookup_chinese_all, lookup_english_all
        
        for row_idx in range(2, sheet.max_row + 1):
            english_cell = sheet.cell(row=row_idx, column=english_col_idx)
            chinese_cell = sheet.cell(row=row_idx, column=chinese_col_idx)
            
            english_val = str(english_cell.value).strip() if english_cell.value else ''
            chinese_val = str(chinese_cell.value).strip() if chinese_cell.value else ''
            
            # Skip if both are filled or both are empty
            if (english_val and chinese_val) or (not english_val and not chinese_val):
                continue
            
            cell_info = {
                'row': row_idx,
                'english_col': english_col_idx,
                'chinese_col': chinese_col_idx,
                'has_english': bool(english_val),
                'has_chinese': bool(chinese_val),
                'english_value': english_val,
                'chinese_value': chinese_val,
                'matches': [],
                'selected': None
            }
            
            if english_val and not chinese_val:
                # Have English, need Chinese
                matches = lookup_chinese_all(english_val)
                cell_info['matches'] = matches
                cell_info['selected'] = matches[0] if matches else None
                cell_info['direction'] = 'en_to_cn'
            elif chinese_val and not english_val:
                # Have Chinese, need English
                matches = lookup_english_all(chinese_val)
                cell_info['matches'] = matches
                cell_info['selected'] = matches[0] if matches else None
                cell_info['direction'] = 'cn_to_en'
            
            cells_to_fill.append(cell_info)
        
        workbook.close()
        
        # Count cells that can be auto-filled (only one match)
        can_auto_fill = sum(1 for c in cells_to_fill if len(c['matches']) == 1)
        needs_selection = sum(1 for c in cells_to_fill if len(c['matches']) > 1)
        no_match = sum(1 for c in cells_to_fill if len(c['matches']) == 0)
        
        return jsonify({
            'cells_to_fill': cells_to_fill,
            'total_to_fill': len(cells_to_fill),
            'can_auto_fill': can_auto_fill,
            'needs_selection': needs_selection,
            'no_match': no_match,
            'english_column': english_col_name,
            'chinese_column': chinese_col_name,
            'english_col_idx': english_col_idx,
            'chinese_col_idx': chinese_col_idx
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@dictionary_bp.route('/apply-fill/<project_id>', methods=['POST'])
@jwt_required()
def apply_dictionary_fill(project_id):
    """
    Apply dictionary fills to the template with user-selected values.
    
    Request body:
    {
        "fills": [
            {"row": 2, "col": 2, "value": "出口"},
            {"row": 3, "col": 1, "value": "Fire Exit"}
        ]
    }
    """
    try:
        import os
        from openpyxl import load_workbook
        
        user_id = get_jwt_identity()
        data = request.get_json()
        
        if not data or 'fills' not in data:
            return jsonify({'error': 'Fills data is required'}), 400
        
        fills = data['fills']
        
        if not isinstance(fills, list):
            return jsonify({'error': 'Fills must be a list'}), 400
        
        # Get the project's template
        template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
        
        if not template:
            return jsonify({'error': 'No template found for this project'}), 404
        
        template_path = template.get('filepath')
        
        if not template_path or not os.path.exists(template_path):
            return jsonify({'error': 'Template file not found'}), 404
        
        workbook = load_workbook(template_path)
        sheet = workbook.active
        
        filled_count = 0
        for fill in fills:
            row = fill.get('row')
            col = fill.get('col')
            value = fill.get('value')
            
            if row and col and value:
                sheet.cell(row=row, column=col, value=value)
                filled_count += 1
        
        workbook.save(template_path)
        workbook.close()
        
        # Log action
        log_action(
            user_id=user_id,
            action='dictionary_fill_applied',
            resource_type='project',
            resource_id=project_id,
            details={'filled_count': filled_count}
        )
        
        return jsonify({
            'message': f'Successfully filled {filled_count} cells',
            'filled_count': filled_count
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
