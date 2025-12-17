import os
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from bson import ObjectId
from app import mongo
from app.models import (
    serialize_doc, 
    create_project_doc, 
    create_template_doc, 
    create_floorplan_doc
)
from app.services.pdf_service import PDFService
from app.services.excel_service import ExcelService

projects_bp = Blueprint('projects', __name__)


def allowed_file(filename, allowed_extensions):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def get_project_with_details(project):
    """Get project with template and floorplans count."""
    if not project:
        return None
    
    result = serialize_doc(project)
    
    # Get template
    template = mongo.db.templates.find_one({'project_id': project['_id']})
    result['template'] = serialize_doc(template)
    
    # Get floorplan count
    result['floorplan_count'] = mongo.db.floorplans.count_documents({'project_id': project['_id']})
    
    return result


def get_project_full_details(project):
    """Get project with all related data."""
    if not project:
        return None
    
    result = serialize_doc(project)
    
    # Get template
    template = mongo.db.templates.find_one({'project_id': project['_id']})
    result['template'] = serialize_doc(template)
    
    # Get floorplans with data counts
    floorplans = list(mongo.db.floorplans.find({'project_id': project['_id']}).sort('floor_number', 1))
    result['floorplans'] = []
    for fp in floorplans:
        fp_dict = serialize_doc(fp)
        
        # Get extracted data with display_text
        extracted = list(mongo.db.extracted_data.find({'floorplan_id': fp['_id']}).sort('shape_index', 1))
        extracted_with_display = []
        for e in extracted:
            e_dict = serialize_doc(e)
            e_dict['display_text'] = e.get('manual_text') or e.get('extracted_text')
            extracted_with_display.append(e_dict)
        
        fp_dict['extracted_data'] = extracted_with_display
        fp_dict['data_count'] = len(extracted)
        result['floorplans'].append(fp_dict)
    
    result['floorplan_count'] = len(floorplans)
    
    return result


@projects_bp.route('', methods=['GET'])
@jwt_required()
def get_projects():
    """Get all projects for the current user."""
    user_id = get_jwt_identity()
    projects = list(mongo.db.projects.find({'user_id': ObjectId(user_id)}).sort('updated_at', -1))
    
    return jsonify({
        'projects': [get_project_with_details(p) for p in projects]
    }), 200


@projects_bp.route('', methods=['POST'])
@jwt_required()
def create_project():
    """Create a new project."""
    user_id = get_jwt_identity()
    data = request.get_json()
    
    if not data or not data.get('name'):
        return jsonify({'error': 'Project name is required'}), 400
    
    project_doc = create_project_doc(
        name=data['name'],
        description=data.get('description', ''),
        user_id=user_id
    )
    
    result = mongo.db.projects.insert_one(project_doc)
    project_id = str(result.inserted_id)
    
    # Refetch the project to get the complete document with _id
    created_project = mongo.db.projects.find_one({'_id': result.inserted_id})
    project_response = get_project_with_details(created_project)
    
    # Explicitly ensure ID is the correct MongoDB ObjectId string
    project_response['id'] = project_id
    
    return jsonify({
        'message': 'Project created successfully',
        'project': project_response
    }), 201


@projects_bp.route('/<project_id>', methods=['GET'])
@jwt_required()
def get_project(project_id):
    """Get a specific project with details."""
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
    
    return jsonify({
        'project': get_project_full_details(project)
    }), 200


@projects_bp.route('/<project_id>', methods=['PUT'])
@jwt_required()
def update_project(project_id):
    """Update a project."""
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
    
    data = request.get_json()
    update_fields = {'updated_at': datetime.utcnow()}
    
    if 'name' in data:
        update_fields['name'] = data['name']
    if 'description' in data:
        update_fields['description'] = data['description']
    if 'status' in data:
        update_fields['status'] = data['status']
    
    mongo.db.projects.update_one({'_id': ObjectId(project_id)}, {'$set': update_fields})
    project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    
    return jsonify({
        'message': 'Project updated successfully',
        'project': get_project_with_details(project)
    }), 200


@projects_bp.route('/<project_id>', methods=['DELETE'])
@jwt_required()
def delete_project(project_id):
    """Delete a project and all related data."""
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
    
    # Delete all related data
    floorplans = list(mongo.db.floorplans.find({'project_id': ObjectId(project_id)}))
    for fp in floorplans:
        mongo.db.extracted_data.delete_many({'floorplan_id': fp['_id']})
    
    mongo.db.floorplans.delete_many({'project_id': ObjectId(project_id)})
    mongo.db.templates.delete_many({'project_id': ObjectId(project_id)})
    mongo.db.projects.delete_one({'_id': ObjectId(project_id)})
    
    return jsonify({'message': 'Project deleted successfully'}), 200


@projects_bp.route('/<project_id>/template', methods=['POST'])
@jwt_required()
def upload_template(project_id):
    """Upload an Excel template for a project."""
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
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename, {'xlsx', 'xls'}):
        return jsonify({'error': 'Only Excel files (.xlsx, .xls) are allowed'}), 400
    
    # Save the file
    filename = secure_filename(file.filename)
    template_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'templates', project_id)
    os.makedirs(template_dir, exist_ok=True)
    filepath = os.path.join(template_dir, filename)
    file.save(filepath)
    
    # Parse template to get columns
    try:
        excel_service = ExcelService()
        columns = excel_service.parse_template(filepath)
    except Exception as e:
        os.remove(filepath)
        return jsonify({'error': f'Failed to parse template: {str(e)}'}), 400
    
    # Remove old template if exists
    old_template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
    if old_template:
        if os.path.exists(old_template.get('filepath', '')):
            os.remove(old_template['filepath'])
        mongo.db.templates.delete_one({'_id': old_template['_id']})
    
    # Create new template
    template_doc = create_template_doc(filename, filepath, project_id, columns)
    result = mongo.db.templates.insert_one(template_doc)
    template_doc['_id'] = result.inserted_id
    
    return jsonify({
        'message': 'Template uploaded successfully',
        'template': serialize_doc(template_doc)
    }), 201


@projects_bp.route('/<project_id>/floorplan', methods=['POST'])
@jwt_required()
def upload_floorplan(project_id):
    """Upload a PDF floorplan for a project."""
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
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename, {'pdf'}):
        return jsonify({'error': 'Only PDF files are allowed'}), 400
    
    # Save the PDF file
    filename = secure_filename(file.filename)
    pdf_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'pdfs', project_id)
    os.makedirs(pdf_dir, exist_ok=True)
    filepath = os.path.join(pdf_dir, filename)
    file.save(filepath)
    
    # Convert PDF to images
    try:
        pdf_service = PDFService()
        image_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'images', project_id)
        os.makedirs(image_dir, exist_ok=True)
        
        pages = pdf_service.convert_to_images(filepath, image_dir)
    except Exception as e:
        os.remove(filepath)
        return jsonify({'error': f'Failed to process PDF: {str(e)}'}), 400
    
    # Create floorplan records for each page
    floorplans = []
    for page_info in pages:
        floorplan_doc = create_floorplan_doc(
            floor_number=page_info['page_number'],
            floor_name=f"Floor {page_info['page_number']}",
            pdf_filename=filename,
            pdf_filepath=filepath,
            image_filepath=page_info['image_path'],
            project_id=project_id
        )
        result = mongo.db.floorplans.insert_one(floorplan_doc)
        floorplan_doc['_id'] = result.inserted_id
        fp_dict = serialize_doc(floorplan_doc)
        fp_dict['data_count'] = 0
        floorplans.append(fp_dict)
    
    # Update project status
    mongo.db.projects.update_one(
        {'_id': ObjectId(project_id)},
        {'$set': {'status': 'in_progress', 'updated_at': datetime.utcnow()}}
    )
    
    return jsonify({
        'message': f'Floorplan uploaded successfully. {len(pages)} pages detected.',
        'floorplans': floorplans
    }), 201


@projects_bp.route('/<project_id>/floorplans', methods=['GET'])
@jwt_required()
def get_floorplans(project_id):
    """Get all floorplans for a project."""
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
    
    floorplans = list(mongo.db.floorplans.find({'project_id': ObjectId(project_id)}).sort('floor_number', 1))
    
    result = []
    for fp in floorplans:
        fp_dict = serialize_doc(fp)
        # Get extracted data
        extracted = list(mongo.db.extracted_data.find({'floorplan_id': fp['_id']}).sort('shape_index', 1))
        
        # Add display_text field (manual_text takes precedence over extracted_text)
        extracted_with_display = []
        for e in extracted:
            e_dict = serialize_doc(e)
            e_dict['display_text'] = e.get('manual_text') or e.get('extracted_text')
            extracted_with_display.append(e_dict)
        
        fp_dict['extracted_data'] = extracted_with_display
        fp_dict['data_count'] = len(extracted)
        result.append(fp_dict)
    
    return jsonify({'floorplans': result}), 200


@projects_bp.route('/<project_id>/floorplans/<floorplan_id>', methods=['GET'])
@jwt_required()
def get_floorplan(project_id, floorplan_id):
    """Get a specific floorplan with extracted data."""
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
    
    try:
        floorplan = mongo.db.floorplans.find_one({
            '_id': ObjectId(floorplan_id),
            'project_id': ObjectId(project_id)
        })
    except:
        return jsonify({'error': 'Invalid floorplan ID'}), 400
    
    if not floorplan:
        return jsonify({'error': 'Floorplan not found'}), 404
    
    fp_dict = serialize_doc(floorplan)
    extracted = list(mongo.db.extracted_data.find({'floorplan_id': floorplan['_id']}).sort('shape_index', 1))
    
    # Add display_text field (manual_text takes precedence over extracted_text)
    extracted_with_display = []
    for e in extracted:
        e_dict = serialize_doc(e)
        e_dict['display_text'] = e.get('manual_text') or e.get('extracted_text')
        extracted_with_display.append(e_dict)
    
    fp_dict['extracted_data'] = extracted_with_display
    fp_dict['data_count'] = len(extracted)
    
    return jsonify({'floorplan': fp_dict}), 200


@projects_bp.route('/<project_id>/floorplans/<floorplan_id>', methods=['PUT'])
@jwt_required()
def update_floorplan(project_id, floorplan_id):
    """Update a floorplan."""
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
    
    try:
        floorplan = mongo.db.floorplans.find_one({
            '_id': ObjectId(floorplan_id),
            'project_id': ObjectId(project_id)
        })
    except:
        return jsonify({'error': 'Invalid floorplan ID'}), 400
    
    if not floorplan:
        return jsonify({'error': 'Floorplan not found'}), 404
    
    data = request.get_json()
    update_fields = {'updated_at': datetime.utcnow()}
    
    if 'floor_name' in data:
        update_fields['floor_name'] = data['floor_name']
    if 'status' in data:
        update_fields['status'] = data['status']
    if 'shape_type' in data:
        update_fields['shape_type'] = data['shape_type']
    
    mongo.db.floorplans.update_one({'_id': ObjectId(floorplan_id)}, {'$set': update_fields})
    floorplan = mongo.db.floorplans.find_one({'_id': ObjectId(floorplan_id)})
    
    fp_dict = serialize_doc(floorplan)
    
    # Get extracted data with display_text
    extracted = list(mongo.db.extracted_data.find({'floorplan_id': floorplan['_id']}).sort('shape_index', 1))
    extracted_with_display = []
    for e in extracted:
        e_dict = serialize_doc(e)
        e_dict['display_text'] = e.get('manual_text') or e.get('extracted_text')
        extracted_with_display.append(e_dict)
    
    fp_dict['extracted_data'] = extracted_with_display
    fp_dict['data_count'] = len(extracted)
    
    return jsonify({
        'message': 'Floorplan updated successfully',
        'floorplan': fp_dict
    }), 200


@projects_bp.route('/<project_id>/floorplans/<floorplan_id>', methods=['DELETE'])
@jwt_required()
def delete_floorplan(project_id, floorplan_id):
    """Delete a floorplan and all related data."""
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
    
    try:
        floorplan = mongo.db.floorplans.find_one({
            '_id': ObjectId(floorplan_id),
            'project_id': ObjectId(project_id)
        })
    except:
        return jsonify({'error': 'Invalid floorplan ID'}), 400
    
    if not floorplan:
        return jsonify({'error': 'Floorplan not found'}), 404
    
    # Delete all extracted data for this floorplan
    mongo.db.extracted_data.delete_many({'floorplan_id': ObjectId(floorplan_id)})
    
    # Delete the image file if it exists
    if floorplan.get('image_filepath') and os.path.exists(floorplan['image_filepath']):
        try:
            os.remove(floorplan['image_filepath'])
        except Exception as e:
            current_app.logger.warning(f"Failed to delete image file: {str(e)}")
    
    # Delete the floorplan document
    mongo.db.floorplans.delete_one({'_id': ObjectId(floorplan_id)})
    
    # Update project timestamp
    mongo.db.projects.update_one(
        {'_id': ObjectId(project_id)},
        {'$set': {'updated_at': datetime.utcnow()}}
    )
    
    return jsonify({'message': 'Floorplan deleted successfully'}), 200
