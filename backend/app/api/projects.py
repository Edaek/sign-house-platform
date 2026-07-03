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
from app.services.ocr_service import OCRService
from app.services.audit_service import log_action
from app.utils.permissions import (
    require_project_access,
    require_project_modify,
    get_current_user,
    is_manager
)

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
    """Get all projects for the current user (or all projects for admins/managers)."""
    user_id = get_jwt_identity()
    user = get_current_user()
    
    # Admins and managers can see all projects
    if is_manager(user):
        projects = list(mongo.db.projects.find({}).sort('updated_at', -1))
        # Add owner information for admins/managers
        result = []
        for p in projects:
            project_dict = get_project_with_details(p)
            # Get owner username
            owner = mongo.db.users.find_one({'_id': p['user_id']})
            project_dict['owner_username'] = owner['username'] if owner else 'Unknown'
            project_dict['owner_id'] = str(p['user_id'])
            result.append(project_dict)
        return jsonify({'projects': result}), 200
    
    # Regular users see their own projects + projects they're members of
    # Get projects where user is the owner
    owned_projects = list(mongo.db.projects.find({'user_id': ObjectId(user_id)}))
    
    # Get projects where user is a member
    memberships = mongo.db.project_members.find({'user_id': ObjectId(user_id)})
    member_project_ids = [m['project_id'] for m in memberships]
    
    if member_project_ids:
        member_projects = list(mongo.db.projects.find({'_id': {'$in': member_project_ids}}))
    else:
        member_projects = []
    
    # Combine and deduplicate (in case user is both owner and member)
    all_project_ids = set()
    combined_projects = []
    
    for p in owned_projects + member_projects:
        if p['_id'] not in all_project_ids:
            all_project_ids.add(p['_id'])
            combined_projects.append(p)
    
    # Sort by updated_at
    combined_projects.sort(key=lambda x: x.get('updated_at', x.get('created_at')), reverse=True)
    
    return jsonify({
        'projects': [get_project_with_details(p) for p in combined_projects]
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
    
    # Log the action
    log_action(
        user_id=user_id,
        action='project_created',
        resource_type='project',
        resource_id=project_id,
        details={'project_name': data['name']}
    )
    
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
@require_project_access
def get_project(project_id, _user=None, _project=None):
    """Get a specific project with details."""
    return jsonify({
        'project': get_project_full_details(_project)
    }), 200


@projects_bp.route('/<project_id>', methods=['PUT'])
@jwt_required()
@require_project_modify
def update_project(project_id, _user=None, _project=None):
    """Update a project."""
    user_id = get_jwt_identity()
    data = request.get_json()
    update_fields = {'updated_at': datetime.utcnow()}
    
    if 'name' in data:
        update_fields['name'] = data['name']
    if 'description' in data:
        update_fields['description'] = data['description']
    if 'status' in data:
        update_fields['status'] = data['status']
    
    mongo.db.projects.update_one({'_id': ObjectId(project_id)}, {'$set': update_fields})
    
    # Log the action
    log_action(
        user_id=user_id,
        action='project_updated',
        resource_type='project',
        resource_id=project_id,
        details={'updated_fields': list(update_fields.keys())}
    )
    
    project = mongo.db.projects.find_one({'_id': ObjectId(project_id)})
    
    return jsonify({
        'message': 'Project updated successfully',
        'project': get_project_with_details(project)
    }), 200


@projects_bp.route('/<project_id>', methods=['DELETE'])
@jwt_required()
@require_project_modify
def delete_project(project_id, _user=None, _project=None):
    """Delete a project and all related data."""
    user_id = get_jwt_identity()
    project_name = _project.get('name', 'Unknown')
    
    # Delete all related data
    floorplans = list(mongo.db.floorplans.find({'project_id': ObjectId(project_id)}))
    for fp in floorplans:
        mongo.db.extracted_data.delete_many({'floorplan_id': fp['_id']})
    
    mongo.db.floorplans.delete_many({'project_id': ObjectId(project_id)})
    mongo.db.templates.delete_many({'project_id': ObjectId(project_id)})
    mongo.db.projects.delete_one({'_id': ObjectId(project_id)})
    
    # Log the action
    log_action(
        user_id=user_id,
        action='project_deleted',
        resource_type='project',
        resource_id=project_id,
        details={'project_name': project_name}
    )
    
    return jsonify({'message': 'Project deleted successfully'}), 200


@projects_bp.route('/<project_id>/template', methods=['POST'])
@jwt_required()
@require_project_modify
def upload_template(project_id, _user=None, _project=None):
    """Upload an Excel template for a project."""
    user_id = get_jwt_identity()
    
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


@projects_bp.route('/<project_id>/template/mapping', methods=['PUT'])
@jwt_required()
@require_project_modify
def save_template_mapping(project_id, _user=None, _project=None):
    """Save floor-to-column mapping for a template."""
    
    # Check if template exists
    template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
    if not template:
        return jsonify({'error': 'No template found for this project'}), 404
    
    data = request.get_json()
    if not data or 'floor_mapping' not in data:
        return jsonify({'error': 'floor_mapping is required'}), 400
    
    floor_mapping = data['floor_mapping']
    
    # Validate floor_mapping is a dict
    if not isinstance(floor_mapping, dict):
        return jsonify({'error': 'floor_mapping must be an object'}), 400
    
    # Update template with floor mapping
    mongo.db.templates.update_one(
        {'_id': template['_id']},
        {'$set': {
            'floor_mapping': floor_mapping,
            'updated_at': datetime.utcnow()
        }}
    )
    
    # Get updated template
    template = mongo.db.templates.find_one({'_id': template['_id']})
    
    return jsonify({
        'message': 'Floor mapping saved successfully',
        'template': serialize_doc(template)
    }), 200


@projects_bp.route('/<project_id>/template/mapping', methods=['GET'])
@jwt_required()
@require_project_access
def get_template_mapping(project_id, _user=None, _project=None):
    """Get floor-to-column mapping for a template."""
    
    # Check if template exists
    template = mongo.db.templates.find_one({'project_id': ObjectId(project_id)})
    if not template:
        return jsonify({'error': 'No template found for this project'}), 404
    
    return jsonify({
        'floor_mapping': template.get('floor_mapping', {}),
        'columns': template.get('columns', [])
    }), 200


@projects_bp.route('/<project_id>/floorplan', methods=['POST'])
@jwt_required()
@require_project_modify
def upload_floorplan(project_id, _user=None, _project=None):
    """Upload a PDF floorplan for a project."""
    user_id = get_jwt_identity()
    
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
    # Initialize OCR service for title extraction (with error handling)
    ocr_service = None
    try:
        ocr_service = OCRService()
    except Exception as e:
        current_app.logger.warning(f"Failed to initialize OCR service for title extraction: {str(e)}")
    
    floorplans = []
    
    for page_info in pages:
        # Try to extract title from the lower-right corner
        extracted_title = None
        
        if ocr_service:
            try:
                extracted_title = ocr_service.extract_title_from_floorplan(
                    page_info['image_path'],
                    x_start_pct=current_app.config.get('TITLE_REGION_X_START', 60),
                    y_start_pct=current_app.config.get('TITLE_REGION_Y_START', 85),
                    width_pct=current_app.config.get('TITLE_REGION_WIDTH', 40),
                    height_pct=current_app.config.get('TITLE_REGION_HEIGHT', 15)
                )
                
                if extracted_title:
                    current_app.logger.info(
                        f"Extracted title for page {page_info['page_number']}: '{extracted_title}'"
                    )
                else:
                    current_app.logger.debug(
                        f"No title extracted for page {page_info['page_number']}, using default"
                    )
            except Exception as e:
                current_app.logger.warning(
                    f"Failed to extract title for page {page_info['page_number']}: {str(e)}"
                )
        
        # Use extracted title if available, otherwise use default floor name
        if extracted_title:
            floor_name = extracted_title
        else:
            floor_name = f"Floor {page_info['page_number']}"
        
        floorplan_doc = create_floorplan_doc(
            floor_number=page_info['page_number'],
            floor_name=floor_name,
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
@require_project_access
def get_floorplans(project_id, _user=None, _project=None):
    """Get all floorplans for a project."""
    
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
@require_project_access
def get_floorplan(project_id, floorplan_id, _user=None, _project=None):
    """Get a specific floorplan with extracted data."""
    
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
@require_project_modify
def update_floorplan(project_id, floorplan_id, _user=None, _project=None):
    """Update a floorplan."""
    
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
@require_project_modify
def delete_floorplan(project_id, floorplan_id, _user=None, _project=None):
    """Delete a floorplan and all related data."""
    
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


@projects_bp.route('/<project_id>/members', methods=['GET'])
@jwt_required()
@require_project_access
def get_project_members(project_id, _user=None, _project=None):
    """Get all members of a project."""
    # Get project owner
    owner = mongo.db.users.find_one({'_id': _project['user_id']})
    owner_info = {
        'id': str(owner['_id']),
        'username': owner['username'],
        'email': owner['email'],
        'role': 'owner',
        'added_at': _project['created_at'].isoformat()
    }
    
    # Get project members
    members_cursor = mongo.db.project_members.find({'project_id': ObjectId(project_id)})
    members = []
    
    for member in members_cursor:
        user = mongo.db.users.find_one({'_id': member['user_id']})
        if user:
            members.append({
                'id': str(user['_id']),
                'username': user['username'],
                'email': user['email'],
                'role': 'member',
                'added_at': member['added_at'].isoformat()
            })
    
    return jsonify({
        'owner': owner_info,
        'members': members
    }), 200


@projects_bp.route('/<project_id>/members', methods=['POST'])
@jwt_required()
@require_project_modify
def add_project_member(project_id, _user=None, _project=None):
    """Add a member to a project."""
    user_id = get_jwt_identity()
    data = request.get_json()
    
    if not data or 'user_id' not in data:
        return jsonify({'error': 'user_id is required'}), 400
    
    member_user_id = data['user_id']
    
    # Check if user exists
    member_user = mongo.db.users.find_one({'_id': ObjectId(member_user_id)})
    if not member_user:
        return jsonify({'error': 'User not found'}), 404
    
    # Check if user is the project owner
    if str(_project['user_id']) == member_user_id:
        return jsonify({'error': 'User is already the project owner'}), 400
    
    # Check if user is already a member
    existing = mongo.db.project_members.find_one({
        'project_id': ObjectId(project_id),
        'user_id': ObjectId(member_user_id)
    })
    
    if existing:
        return jsonify({'error': 'User is already a member of this project'}), 400
    
    # Add the member
    from app.models import create_project_member_doc
    member_doc = create_project_member_doc(project_id, member_user_id, 'member', user_id)
    mongo.db.project_members.insert_one(member_doc)
    
    # Log the action
    log_action(
        user_id=user_id,
        action='project_member_added',
        resource_type='project',
        resource_id=project_id,
        details={
            'project_name': _project['name'],
            'member_username': member_user['username'],
            'member_id': member_user_id
        }
    )
    
    return jsonify({
        'message': 'Member added successfully',
        'member': {
            'id': str(member_user['_id']),
            'username': member_user['username'],
            'email': member_user['email']
        }
    }), 201


@projects_bp.route('/<project_id>/members/<member_user_id>', methods=['DELETE'])
@jwt_required()
@require_project_modify
def remove_project_member(project_id, member_user_id, _user=None, _project=None):
    """Remove a member from a project."""
    user_id = get_jwt_identity()
    
    # Check if member exists
    member = mongo.db.project_members.find_one({
        'project_id': ObjectId(project_id),
        'user_id': ObjectId(member_user_id)
    })
    
    if not member:
        return jsonify({'error': 'User is not a member of this project'}), 404
    
    # Get member user info for logging
    member_user = mongo.db.users.find_one({'_id': ObjectId(member_user_id)})
    
    # Remove the member
    mongo.db.project_members.delete_one({'_id': member['_id']})
    
    # Log the action
    log_action(
        user_id=user_id,
        action='project_member_removed',
        resource_type='project',
        resource_id=project_id,
        details={
            'project_name': _project['name'],
            'member_username': member_user['username'] if member_user else 'Unknown',
            'member_id': member_user_id
        }
    )
    
    return jsonify({'message': 'Member removed successfully'}), 200


@projects_bp.route('/<project_id>/re-extract-titles', methods=['POST'])
@jwt_required()
@require_project_modify
def re_extract_titles(project_id, _user=None, _project=None):
    """Re-extract titles from OCR for all floorplans in a project."""
    floorplans = list(mongo.db.floorplans.find({
        'project_id': ObjectId(project_id)
    }).sort('floor_number', 1))

    if not floorplans:
        return jsonify({'error': 'No floorplans found'}), 404

    ocr_service = OCRService()
    updated = []

    for fp in floorplans:
        image_path = fp.get('image_filepath')
        if not image_path or not os.path.exists(image_path):
            continue

        try:
            extracted_title = ocr_service.extract_title_from_floorplan(
                image_path,
                x_start_pct=current_app.config.get('TITLE_REGION_X_START', 60),
                y_start_pct=current_app.config.get('TITLE_REGION_Y_START', 85),
                width_pct=current_app.config.get('TITLE_REGION_WIDTH', 40),
                height_pct=current_app.config.get('TITLE_REGION_HEIGHT', 15)
            )

            if extracted_title and extracted_title != fp.get('floor_name'):
                mongo.db.floorplans.update_one(
                    {'_id': fp['_id']},
                    {'$set': {'floor_name': extracted_title, 'updated_at': datetime.utcnow()}}
                )
                updated.append({
                    'id': str(fp['_id']),
                    'old_name': fp.get('floor_name'),
                    'new_name': extracted_title
                })
        except Exception as e:
            current_app.logger.warning(f"Failed to re-extract title for floorplan {fp['_id']}: {e}")

    return jsonify({
        'message': f'Re-extracted titles: {len(updated)} updated out of {len(floorplans)}',
        'updated': updated
    }), 200
