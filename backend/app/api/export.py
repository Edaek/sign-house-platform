import os
from flask import Blueprint, request, jsonify, send_file, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from app import mongo
from app.models import serialize_doc
from app.services.excel_service import ExcelService

export_bp = Blueprint('export', __name__)


@export_bp.route('/preview/<project_id>', methods=['GET'])
@jwt_required()
def preview_export(project_id):
    """Preview all extracted data for a project."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Get all extracted data from all floorplans
    floorplans = list(mongo.db.floorplans.find({
        'project_id': ObjectId(project_id)
    }).sort('floor_number', 1))
    
    all_data = []
    summary_groups = {}  # For cross-floor summary
    
    for fp in floorplans:
        extracted = list(mongo.db.extracted_data.find({
            'floorplan_id': fp['_id']
        }).sort('shape_index', 1))
        
        for data in extracted:
            display_text = data.get('manual_text') or data.get('extracted_text') or ''
            quantity = data.get('quantity', 1)
            merged_count = data.get('merged_count', 1)
            
            # Add to per-floor data
            all_data.append({
                'floor_number': fp['floor_number'],
                'floor_name': fp['floor_name'],
                'shape_index': data['shape_index'],
                'text': display_text,
                'quantity': quantity,
                'merged_count': merged_count,
                'confidence': round((data.get('confidence') or 0) * 100, 1),
                'is_manual': data.get('is_manual', False)
            })
            
            # Group for cross-floor summary
            normalized_text = display_text.strip().lower()
            if normalized_text:  # Skip empty text
                if normalized_text not in summary_groups:
                    summary_groups[normalized_text] = {
                        'text': display_text,  # Keep original case from first occurrence
                        'total_quantity': 0,
                        'floors': set(),
                        'floor_details': []
                    }
                
                summary_groups[normalized_text]['total_quantity'] += quantity
                summary_groups[normalized_text]['floors'].add(fp['floor_number'])
                summary_groups[normalized_text]['floor_details'].append({
                    'floor_number': fp['floor_number'],
                    'floor_name': fp['floor_name'],
                    'quantity': quantity
                })
    
    # Convert summary groups to list and sort
    summary = []
    for normalized_text, group_data in summary_groups.items():
        floors_list = sorted(list(group_data['floors']))
        summary.append({
            'text': group_data['text'],
            'total_quantity': group_data['total_quantity'],
            'floor_count': len(floors_list),
            'floors': floors_list,
            'floor_details': group_data['floor_details']
        })
    
    # Sort summary by text
    summary.sort(key=lambda x: x['text'].lower())
    
    # Get template columns if available
    columns = []
    template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
    if template:
        columns = template.get('columns', [])
    
    return jsonify({
        'project': serialize_doc(project),
        'columns': columns,
        'data': all_data,
        'total_items': len(all_data),
        'summary': summary,
        'summary_stats': {
            'unique_items': len(summary),
            'total_floors': len(floorplans)
        }
    }), 200


@export_bp.route('/excel/<project_id>', methods=['POST'])
@jwt_required()
def export_to_excel(project_id):
    """Export project data to Excel using the template."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Get column mapping from request
    data = request.get_json() or {}
    column_mapping = data.get('column_mapping', {})
    
    # Collect all extracted data
    floorplans = list(mongo.db.floorplans.find({
        'project_id': ObjectId(project_id)
    }).sort('floor_number', 1))
    
    all_data = []
    for fp in floorplans:
        extracted = list(mongo.db.extracted_data.find({
            'floorplan_id': fp['_id']
        }).sort('shape_index', 1))
        
        for item in extracted:
            display_text = item.get('manual_text') or item.get('extracted_text') or ''
            row = {
                'floor_number': fp['floor_number'],
                'floor_name': fp['floor_name'],
                'shape_index': item['shape_index'] + 1,
                'text': display_text,
                'quantity': item.get('quantity', 1),
                'confidence': round((item.get('confidence') or 0) * 100, 1),
                'x': item['x'],
                'y': item['y'],
                'width': item['width'],
                'height': item['height']
            }
            all_data.append(row)
    
    try:
        excel_service = ExcelService()
        
        # Use template if available
        template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
        template_path = template.get('filepath') if template else None
        floor_mapping = template.get('floor_mapping', {}) if template else {}
        
        # Debug logging
        current_app.logger.info(f'Template path: {template_path}')
        current_app.logger.info(f'Floor mapping: {floor_mapping}')
        current_app.logger.info(f'Data count: {len(all_data)}')
        
        # Create export file
        output_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'exports')
        os.makedirs(output_dir, exist_ok=True)
        
        # Sanitize project name for filename
        import re
        safe_name = re.sub(r'[^\w\s-]', '', project["name"]).strip().replace(' ', '_')
        output_path = os.path.join(output_dir, f'export_{project_id}_{safe_name}.xlsx')
        
        # Use template mapping if both template and floor mapping are available
        if template_path and floor_mapping:
            excel_service.export_with_template_mapping(
                all_data,
                output_path,
                template_path,
                floor_mapping
            )
        elif template_path:
            # Template exists but no floor mapping - return error with helpful message
            return jsonify({
                'error': 'Floor mapping not configured',
                'message': 'Please configure floor-to-column mapping before exporting',
                'template_columns': template.get('columns', [])
            }), 400
        else:
            # No template - use default export
            excel_service.export_data(
                all_data,
                output_path,
                template_path=None,
                column_mapping=column_mapping
            )
        
        return send_file(
            output_path,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'{project["name"]}_export.xlsx'
        )
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f'Export failed: {str(e)}\n{error_trace}')
        return jsonify({'error': f'Export failed: {str(e)}'}), 500


@export_bp.route('/csv/<project_id>', methods=['POST'])
@jwt_required()
def export_to_csv(project_id):
    """Export project data to CSV."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Get options from request
    data = request.get_json() or {}
    include_metadata = data.get('include_metadata', True)
    
    # Collect all extracted data
    floorplans = list(mongo.db.floorplans.find({
        'project_id': ObjectId(project_id)
    }).sort('floor_number', 1))
    
    all_data = []
    for fp in floorplans:
        extracted = list(mongo.db.extracted_data.find({
            'floorplan_id': fp['_id']
        }).sort('shape_index', 1))
        
        for item in extracted:
            display_text = item.get('manual_text') or item.get('extracted_text') or ''
            row = {
                'floor_number': fp['floor_number'],
                'floor_name': fp['floor_name'],
                'item_number': item['shape_index'] + 1,
                'text': display_text,
                'quantity': item.get('quantity', 1)
            }
            if include_metadata:
                row['confidence'] = round((item.get('confidence') or 0) * 100, 1)
                row['x'] = item['x']
                row['y'] = item['y']
                row['width'] = item['width']
                row['height'] = item['height']
            all_data.append(row)
    
    try:
        excel_service = ExcelService()
        
        output_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'exports')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f'export_{project_id}_{project["name"]}.csv')
        
        excel_service.export_to_csv(all_data, output_path)
        
        return send_file(
            output_path,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'{project["name"]}_export.csv'
        )
        
    except Exception as e:
        return jsonify({'error': f'Export failed: {str(e)}'}), 500


@export_bp.route('/complete/<project_id>', methods=['POST'])
@jwt_required()
def mark_complete(project_id):
    """Mark a project as completed."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Check if all floorplans are completed
    incomplete = mongo.db.floorplans.count_documents({
        'project_id': ObjectId(project_id),
        'status': {'$ne': 'completed'}
    })
    
    if incomplete > 0:
        return jsonify({
            'warning': f'{incomplete} floor(s) not yet completed',
            'project': serialize_doc(project)
        }), 200
    
    from datetime import datetime
    mongo.db.projects.update_one(
        {'_id': ObjectId(project_id)},
        {'$set': {'status': 'completed', 'updated_at': datetime.utcnow()}}
    )
    
    project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    
    return jsonify({
        'message': 'Project marked as completed',
        'project': serialize_doc(project)
    }), 200


@export_bp.route('/template-data/<project_id>', methods=['GET'])
@jwt_required()
def get_template_data(project_id):
    """Get template data merged with OCR extracted data."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Get template
    template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
    if not template:
        return jsonify({'error': 'No template uploaded for this project'}), 404
    
    template_path = template.get('filepath')
    if not template_path or not os.path.exists(template_path):
        return jsonify({'error': 'Template file not found'}), 404
    
    try:
        excel_service = ExcelService()
        
        # Read template data
        template_data = excel_service.read_template_data(template_path)
        
        # Get OCR extracted data
        floorplans = list(mongo.db.floorplans.find({
            'project_id': ObjectId(project_id)
        }).sort('floor_number', 1))
        
        ocr_data = []
        for fp in floorplans:
            extracted = list(mongo.db.extracted_data.find({
                'floorplan_id': fp['_id']
            }).sort('shape_index', 1))
            
            for item in extracted:
                display_text = item.get('manual_text') or item.get('extracted_text') or ''
                ocr_data.append({
                    'floor_number': fp['floor_number'],
                    'floor_name': fp['floor_name'],  # Include floor name for auto-matching
                    'text': display_text,
                    'quantity': item.get('quantity', 1)
                })
        
        # Get floor mapping (optional - auto-matching will work without it)
        floor_mapping = template.get('floor_mapping', {})
        
        # Merge OCR data into template (auto-matches floor names to columns)
        template_data = excel_service.merge_with_ocr_data(
            template_data,
            ocr_data,
            floor_mapping  # Pass mapping as optional override
        )
        
        return jsonify({
            'template': serialize_doc(template),
            'data': template_data
        }), 200
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f'Failed to read template data: {str(e)}\n{error_trace}')
        return jsonify({'error': f'Failed to read template: {str(e)}'}), 500


@export_bp.route('/template-data/<project_id>', methods=['PUT'])
@jwt_required()
def update_template_data(project_id):
    """Update cells in the template file."""
    user_id = get_jwt_identity()
    
    try:
        project = mongo.db.projects.find_one({
            '_id': ObjectId(project_id),
            'user_id': ObjectId(user_id)
        })
    except:
        return jsonify({'error': 'Invalid project ID'}), 400
    
    if not project:
        return jsonify({'error': 'Project not found'}), 404
    
    # Get template
    template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
    if not template:
        return jsonify({'error': 'No template uploaded for this project'}), 404
    
    template_path = template.get('filepath')
    if not template_path or not os.path.exists(template_path):
        return jsonify({'error': 'Template file not found'}), 404
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        excel_service = ExcelService()
        
        # Support both single cell and batch updates
        if 'updates' in data:
            # Batch update
            updates = data['updates']
            if not isinstance(updates, list):
                return jsonify({'error': 'updates must be an array'}), 400
            
            results = excel_service.update_cells_batch(template_path, updates)
            return jsonify({
                'message': f'Updated {len(results)} cells',
                'cells': results
            }), 200
        else:
            # Single cell update
            row = data.get('row')
            col = data.get('col')
            value = data.get('value')
            
            if row is None or col is None:
                return jsonify({'error': 'row and col are required'}), 400
            
            result = excel_service.update_cell(template_path, row, col, value)
            return jsonify({
                'message': 'Cell updated',
                'cell': result
            }), 200
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f'Failed to update template: {str(e)}\n{error_trace}')
        return jsonify({'error': f'Failed to update template: {str(e)}'}), 500