import os
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from app import mongo
from app.models import serialize_doc, create_extracted_data_doc
from app.services.cv_service import CVService
from app.services.ocr_service import OCRService

processing_bp = Blueprint('processing', __name__)


@processing_bp.route('/detect/<floorplan_id>', methods=['POST'])
@jwt_required()
def detect_shapes(floorplan_id):
    """Detect shapes in a floorplan image."""
    user_id = get_jwt_identity()
    
    try:
        floorplan = mongo.db.floorplans.find_one({'_id': ObjectId(floorplan_id)})
    except:
        return jsonify({'error': 'Invalid floorplan ID'}), 400
    
    if not floorplan:
        return jsonify({'error': 'Floorplan not found'}), 404
    
    project = mongo.db.projects.find_one({
        '_id': floorplan['project_id'],
        'user_id': ObjectId(user_id)
    })
    if not project:
        return jsonify({'error': 'Access denied'}), 403
    
    data = request.get_json() or {}
    # Default to rectangle detection (circle detection is disabled for now)
    shape_type = data.get('shape_type', 'rectangle')
    
    if not os.path.exists(floorplan.get('image_filepath', '')):
        return jsonify({'error': 'Floorplan image not found'}), 404
    
    try:
        cv_service = CVService()
        
        # Circle detection is disabled - always use rectangle detection
        # Use the new red rectangle detection method for better accuracy
        # on floor plans with red-bordered label boxes
        if shape_type == 'circle':
            # Circle detection is temporarily disabled
            # Return error message to inform user
            return jsonify({
                'error': 'Circle detection is temporarily disabled. Please use rectangle detection.'
            }), 400
        else:
            # Use red rectangle detection (detects red-bordered boxes with white backgrounds)
            shapes = cv_service.detect_red_rectangles(floorplan['image_filepath'])
            detected_type = 'rectangle'
        
        # Update floorplan
        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {
                'shape_type': detected_type,
                'status': 'processing',
                'updated_at': datetime.utcnow()
            }}
        )
        
        # Clear old extracted data
        mongo.db.extracted_data.delete_many({'floorplan_id': ObjectId(floorplan_id)})
        
        # Create extracted data records for each shape
        extracted_records = []
        for idx, shape in enumerate(shapes):
            shape_data = None
            if 'radius' in shape:
                shape_data = {
                    'radius': shape['radius'],
                    'center_x': shape['center_x'],
                    'center_y': shape['center_y']
                }
            
            doc = create_extracted_data_doc(
                shape_index=idx,
                shape_type=detected_type,
                x=shape['x'],
                y=shape['y'],
                width=shape['width'],
                height=shape['height'],
                floorplan_id=floorplan_id,
                shape_data=shape_data
            )
            
            result = mongo.db.extracted_data.insert_one(doc)
            doc['_id'] = result.inserted_id
            extracted_records.append(serialize_doc(doc))
        
        return jsonify({
            'message': f'Detected {len(shapes)} {detected_type}s',
            'shape_type': detected_type,
            'shapes': extracted_records
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Shape detection failed: {str(e)}'}), 500


@processing_bp.route('/ocr/<floorplan_id>', methods=['POST'])
@jwt_required()
def extract_text(floorplan_id):
    """Run OCR on all detected shapes in a floorplan."""
    user_id = get_jwt_identity()
    
    try:
        floorplan = mongo.db.floorplans.find_one({'_id': ObjectId(floorplan_id)})
    except:
        return jsonify({'error': 'Invalid floorplan ID'}), 400
    
    if not floorplan:
        return jsonify({'error': 'Floorplan not found'}), 404
    
    project = mongo.db.projects.find_one({
        '_id': floorplan['project_id'],
        'user_id': ObjectId(user_id)
    })
    if not project:
        return jsonify({'error': 'Access denied'}), 403
    
    if not os.path.exists(floorplan.get('image_filepath', '')):
        return jsonify({'error': 'Floorplan image not found'}), 404
    
    extracted_data = list(mongo.db.extracted_data.find({'floorplan_id': ObjectId(floorplan_id)}))
    
    if not extracted_data:
        return jsonify({'error': 'No shapes detected. Please run shape detection first.'}), 400
    
    try:
        ocr_service = OCRService()
        
        results = []
        for data in extracted_data:
            # Extract text from the shape region (use label_mode for red-bordered labels)
            text, confidence = ocr_service.extract_text_from_region(
                floorplan['image_filepath'],
                data['x'], data['y'], data['width'], data['height'],
                padding=0,  # No padding needed for labels (border removed in preprocessing)
                label_mode=True  # Use specialized label preprocessing
            )
            
            mongo.db.extracted_data.update_one(
                {'_id': data['_id']},
                {'$set': {
                    'extracted_text': text,
                    'confidence': confidence,
                    'updated_at': datetime.utcnow()
                }}
            )
            
            data['extracted_text'] = text
            data['confidence'] = confidence
            data['display_text'] = data.get('manual_text') or text
            results.append(serialize_doc(data))
        
        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {'status': 'completed', 'updated_at': datetime.utcnow()}}
        )
        
        return jsonify({
            'message': f'OCR completed for {len(results)} shapes',
            'results': results
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'OCR failed: {str(e)}'}), 500


@processing_bp.route('/ocr-region/<floorplan_id>', methods=['POST'])
@jwt_required()
def ocr_manual_region(floorplan_id):
    """Run OCR on a manually selected region."""
    user_id = get_jwt_identity()
    
    try:
        floorplan = mongo.db.floorplans.find_one({'_id': ObjectId(floorplan_id)})
    except:
        return jsonify({'error': 'Invalid floorplan ID'}), 400
    
    if not floorplan:
        return jsonify({'error': 'Floorplan not found'}), 404
    
    project = mongo.db.projects.find_one({
        '_id': floorplan['project_id'],
        'user_id': ObjectId(user_id)
    })
    if not project:
        return jsonify({'error': 'Access denied'}), 403
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Region coordinates required'}), 400
    
    x = data.get('x')
    y = data.get('y')
    width = data.get('width')
    height = data.get('height')
    
    if not all([x is not None, y is not None, width, height]):
        return jsonify({'error': 'x, y, width, and height are required'}), 400
    
    if not os.path.exists(floorplan.get('image_filepath', '')):
        return jsonify({'error': 'Floorplan image not found'}), 404
    
    try:
        ocr_service = OCRService()
        # Use label_mode for better accuracy on red-bordered labels
        text, confidence = ocr_service.extract_text_from_region(
            floorplan['image_filepath'],
            int(x), int(y), int(width), int(height),
            padding=0,
            label_mode=True
        )
        
        # Get next shape index
        max_doc = mongo.db.extracted_data.find_one(
            {'floorplan_id': ObjectId(floorplan_id)},
            sort=[('shape_index', -1)]
        )
        next_index = (max_doc['shape_index'] + 1) if max_doc else 0
        
        # Create new extracted data record
        doc = create_extracted_data_doc(
            shape_index=next_index,
            shape_type='manual',
            x=int(x),
            y=int(y),
            width=int(width),
            height=int(height),
            floorplan_id=floorplan_id
        )
        doc['extracted_text'] = text
        doc['confidence'] = confidence
        doc['is_manual'] = True
        
        result = mongo.db.extracted_data.insert_one(doc)
        doc['_id'] = result.inserted_id
        doc['display_text'] = text
        
        return jsonify({
            'message': 'Text extracted successfully',
            'result': serialize_doc(doc)
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'OCR failed: {str(e)}'}), 500


@processing_bp.route('/data/<data_id>', methods=['PUT'])
@jwt_required()
def update_extracted_data(data_id):
    """Update extracted data (e.g., manual text override)."""
    user_id = get_jwt_identity()
    
    try:
        extracted = mongo.db.extracted_data.find_one({'_id': ObjectId(data_id)})
    except:
        return jsonify({'error': 'Invalid data ID'}), 400
    
    if not extracted:
        return jsonify({'error': 'Data not found'}), 404
    
    floorplan = mongo.db.floorplans.find_one({'_id': extracted['floorplan_id']})
    project = mongo.db.projects.find_one({
        '_id': floorplan['project_id'],
        'user_id': ObjectId(user_id)
    })
    if not project:
        return jsonify({'error': 'Access denied'}), 403
    
    data = request.get_json()
    update_fields = {'updated_at': datetime.utcnow()}
    
    if 'manual_text' in data:
        update_fields['manual_text'] = data['manual_text']
        update_fields['is_manual'] = True
    
    mongo.db.extracted_data.update_one({'_id': ObjectId(data_id)}, {'$set': update_fields})
    
    extracted = mongo.db.extracted_data.find_one({'_id': ObjectId(data_id)})
    result = serialize_doc(extracted)
    result['display_text'] = extracted.get('manual_text') or extracted.get('extracted_text')
    
    return jsonify({
        'message': 'Data updated successfully',
        'result': result
    }), 200


@processing_bp.route('/data/<data_id>', methods=['DELETE'])
@jwt_required()
def delete_extracted_data(data_id):
    """Delete an extracted data record."""
    user_id = get_jwt_identity()
    
    try:
        extracted = mongo.db.extracted_data.find_one({'_id': ObjectId(data_id)})
    except:
        return jsonify({'error': 'Invalid data ID'}), 400
    
    if not extracted:
        return jsonify({'error': 'Data not found'}), 404
    
    floorplan = mongo.db.floorplans.find_one({'_id': extracted['floorplan_id']})
    project = mongo.db.projects.find_one({
        '_id': floorplan['project_id'],
        'user_id': ObjectId(user_id)
    })
    if not project:
        return jsonify({'error': 'Access denied'}), 403
    
    mongo.db.extracted_data.delete_one({'_id': ObjectId(data_id)})
    
    return jsonify({'message': 'Data deleted successfully'}), 200


@processing_bp.route('/image/<floorplan_id>', methods=['GET'])
@jwt_required()
def get_floorplan_image(floorplan_id):
    """Get the floorplan image."""
    user_id = get_jwt_identity()
    
    try:
        floorplan = mongo.db.floorplans.find_one({'_id': ObjectId(floorplan_id)})
    except:
        return jsonify({'error': 'Invalid floorplan ID'}), 400
    
    if not floorplan:
        return jsonify({'error': 'Floorplan not found'}), 404
    
    project = mongo.db.projects.find_one({
        '_id': floorplan['project_id'],
        'user_id': ObjectId(user_id)
    })
    if not project:
        return jsonify({'error': 'Access denied'}), 403
    
    if not os.path.exists(floorplan.get('image_filepath', '')):
        return jsonify({'error': 'Image not found'}), 404
    
    return send_file(floorplan['image_filepath'], mimetype='image/png')
