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
    for fp in floorplans:
        extracted = list(mongo.db.extracted_data.find({
            'floorplan_id': fp['_id']
        }).sort('shape_index', 1))
        
        for data in extracted:
            display_text = data.get('manual_text') or data.get('extracted_text') or ''
            all_data.append({
                'floor_number': fp['floor_number'],
                'floor_name': fp['floor_name'],
                'shape_index': data['shape_index'],
                'text': display_text,
                'quantity': data.get('quantity', 1),
                'confidence': round((data.get('confidence') or 0) * 100, 1),
                'is_manual': data.get('is_manual', False)
            })
    
    # Get template columns if available
    columns = []
    template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
    if template:
        columns = template.get('columns', [])
    
    return jsonify({
        'project': serialize_doc(project),
        'columns': columns,
        'data': all_data,
        'total_items': len(all_data)
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
        
        # Create export file
        output_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'exports')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f'export_{project_id}_{project["name"]}.xlsx')
        
        excel_service.export_data(
            all_data,
            output_path,
            template_path=template_path,
            column_mapping=column_mapping
        )
        
        return send_file(
            output_path,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'{project["name"]}_export.xlsx'
        )
        
    except Exception as e:
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
