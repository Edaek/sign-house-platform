import os
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from bson import ObjectId
from app import mongo
from app.models import (
    serialize_doc, 
    create_extracted_data_doc, 
    create_floorplan_doc,
    create_processing_job_doc,
    create_processing_file_doc,
    processing_job_to_dict,
    create_shape_template_doc,
    shape_template_to_dict
)
from app.services.cv_service import CVService
from app.services.ocr_service import OCRService, is_valid_sign_code, clean_ocr_text
from app.services.batch_processor import start_batch_processing
from app.utils.permissions import require_project_access, require_project_modify

processing_bp = Blueprint('processing', __name__)


def allowed_file(filename, allowed_extensions):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


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
    # Default to auto detection - will check for sample circle in upper-right corner
    shape_type = data.get('shape_type', 'auto')
    
    if not os.path.exists(floorplan.get('image_filepath', '')):
        return jsonify({'error': 'Floorplan image not found'}), 404
    
    try:
        cv_service = CVService()
        ocr_service = OCRService()
        image_path = floorplan['image_filepath']

        # Auto-detect: check if there's a sample circle in upper-right corner
        if shape_type == 'auto':
            if cv_service.has_sample_circle(image_path):
                shape_type = 'circle'
            else:
                shape_type = 'rectangle'

        if shape_type == 'circle':
            shapes = cv_service.detect_circles_by_template(image_path)
            detected_type = 'circle'
        else:
            shapes = cv_service.detect_red_rectangles(image_path)
            detected_type = 'rectangle'

        # Learned template matching pass
        learned_shapes = []
        try:
            active_templates = list(mongo.db.shape_templates.find({'is_active': True}))
            if active_templates:
                raw_learned = cv_service.detect_from_learned_templates(
                    image_path, active_templates, shape_type=detected_type
                )
                learned_shapes = cv_service.deduplicate_with_existing(raw_learned, shapes)
                if learned_shapes:
                    current_app.logger.info(
                        f"Learned templates added {len(learned_shapes)} new detections"
                    )
        except Exception as tmpl_err:
            current_app.logger.warning(f"Learned template matching failed: {tmpl_err}")

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

        # Combine standard and learned shapes
        all_shapes = shapes + learned_shapes

        # --- Merged OCR + filter + save ---
        is_circle = detected_type == 'circle'
        ocr_results = []

        for idx, shape in enumerate(all_shapes):
            # Run full OCR (higher quality than the quick cross-check in detection)
            if is_circle and shape.get('center_x') is not None:
                text, confidence = ocr_service.extract_text_from_circle(
                    image_path,
                    shape['center_x'], shape['center_y'], shape['radius'],
                    padding=10
                )
            else:
                text, confidence = ocr_service.extract_text_from_region(
                    image_path,
                    shape['x'], shape['y'], shape['width'], shape['height'],
                    padding=0, label_mode=True, capture_adjacent=False
                )

            cleaned = clean_ocr_text(text)
            if not is_valid_sign_code(cleaned):
                continue

            quantity = ocr_service.find_multiplier_near_region(
                image_path,
                shape['x'], shape['y'], shape['width'], shape['height']
            )

            shape_data = None
            if 'radius' in shape:
                shape_data = {
                    'radius': shape['radius'],
                    'center_x': shape['center_x'],
                    'center_y': shape['center_y'],
                }
                if 'confidence' in shape:
                    shape_data['confidence'] = shape['confidence']

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
            doc['extracted_text'] = cleaned
            doc['confidence'] = confidence
            doc['quantity'] = quantity

            if shape.get('detection_method') == 'learned':
                doc['detection_method'] = 'learned'
                doc['template_id'] = shape.get('template_id')

            result = mongo.db.extracted_data.insert_one(doc)
            doc['_id'] = result.inserted_id
            doc['display_text'] = text
            ocr_results.append(doc)

        # Group duplicates
        grouping_result = ocr_service.group_ocr_results(ocr_results)
        grouped_results = grouping_result['grouped']
        deleted_ids = grouping_result['deleted_ids']
        merge_info = grouping_result['merge_info']

        for res in grouped_results:
            result_id = res['_id']
            if str(result_id) in merge_info:
                info = merge_info[str(result_id)]
                mongo.db.extracted_data.update_one(
                    {'_id': result_id},
                    {'$set': {
                        'quantity': info['total_quantity'],
                        'merged_count': info['merged_count'],
                        'original_shape_indices': info['original_indices'],
                        'all_bounding_boxes': info['all_bounding_boxes'],
                        'updated_at': datetime.utcnow()
                    }}
                )
                res['merged_count'] = info['merged_count']
                res['original_shape_indices'] = info['original_indices']
                res['all_bounding_boxes'] = info['all_bounding_boxes']

        if deleted_ids:
            mongo.db.extracted_data.delete_many({'_id': {'$in': deleted_ids}})

        # Increment match_count for templates that produced valid detections
        matched_template_ids = set()
        for res in grouped_results:
            tid = res.get('template_id')
            if tid and res.get('detection_method') == 'learned':
                matched_template_ids.add(tid)
        for tid in matched_template_ids:
            try:
                mongo.db.shape_templates.update_one(
                    {'_id': ObjectId(tid)},
                    {'$inc': {'match_count': 1}}
                )
            except Exception:
                pass

        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {'status': 'completed', 'updated_at': datetime.utcnow()}}
        )

        response_results = [serialize_doc(d) for d in grouped_results]
        for res in response_results:
            res['display_text'] = res.get('manual_text') or res.get('extracted_text')

        total_merged = sum(info['merged_count'] for info in merge_info.values())
        learned_count = sum(1 for r in grouped_results if r.get('detection_method') == 'learned')
        message = f'Detected and OCR\'d {len(response_results)} unique {detected_type}s'
        if deleted_ids:
            message += f' ({total_merged} original detections grouped)'
        if learned_count:
            message += f' ({learned_count} from learned templates)'

        return jsonify({
            'message': message,
            'shape_type': detected_type,
            'shapes': response_results,
            'grouping_info': {
                'total_unique': len(response_results),
                'total_detected': len(all_shapes),
                'merged_count': len(deleted_ids),
                'learned_count': learned_count
            }
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
        is_circle = floorplan.get('shape_type') == 'circle'
        
        for data in extracted_data:
            if is_circle and data.get('shape_data'):
                sd = data['shape_data']
                text, confidence = ocr_service.extract_text_from_circle(
                    floorplan['image_filepath'],
                    sd.get('center_x', data['x'] + data['width'] // 2),
                    sd.get('center_y', data['y'] + data['height'] // 2),
                    sd.get('radius', data['width'] // 2),
                    padding=3
                )
            else:
                text, confidence = ocr_service.extract_text_from_region(
                    floorplan['image_filepath'],
                    data['x'], data['y'], data['width'], data['height'],
                    padding=0,
                    label_mode=True,
                    capture_adjacent=False
                )
            
            # Search for multiplier in nearby regions (x2, x3, etc.)
            quantity = ocr_service.find_multiplier_near_region(
                floorplan['image_filepath'],
                data['x'], data['y'], data['width'], data['height']
            )
            
            # Log for debugging
            if quantity > 1:
                current_app.logger.info(f"Found multiplier x{quantity} near rectangle at ({data['x']}, {data['y']}): '{text}'")
            
            mongo.db.extracted_data.update_one(
                {'_id': data['_id']},
                {'$set': {
                    'extracted_text': text,
                    'confidence': confidence,
                    'quantity': quantity,
                    'updated_at': datetime.utcnow()
                }}
            )
            
            data['extracted_text'] = text
            data['confidence'] = confidence
            data['quantity'] = quantity
            data['display_text'] = data.get('manual_text') or text
            results.append(data)
        
        # Group OCR results by identical text
        grouping_result = ocr_service.group_ocr_results(results)
        grouped_results = grouping_result['grouped']
        deleted_ids = grouping_result['deleted_ids']
        merge_info = grouping_result['merge_info']
        
        # Update grouped records in database with new quantities and add to in-memory objects
        for result in grouped_results:
            result_id = result['_id']
            if str(result_id) in merge_info:
                # This result was merged with others
                info = merge_info[str(result_id)]
                
                # Update database
                mongo.db.extracted_data.update_one(
                    {'_id': result_id},
                    {'$set': {
                        'quantity': info['total_quantity'],
                        'merged_count': info['merged_count'],
                        'original_shape_indices': info['original_indices'],
                        'all_bounding_boxes': info['all_bounding_boxes'],
                        'updated_at': datetime.utcnow()
                    }}
                )
                
                # Also update the in-memory object so it's included in the response
                result['merged_count'] = info['merged_count']
                result['original_shape_indices'] = info['original_indices']
                result['all_bounding_boxes'] = info['all_bounding_boxes']
                
                current_app.logger.info(
                    f"Merged {info['merged_count']} items with text '{result.get('extracted_text')}' "
                    f"into one with total quantity {info['total_quantity']}"
                )
        
        # Delete duplicate records from database
        if deleted_ids:
            mongo.db.extracted_data.delete_many({'_id': {'$in': deleted_ids}})
            current_app.logger.info(f"Deleted {len(deleted_ids)} duplicate OCR results")
        
        # Prepare response with serialized grouped results
        response_results = [serialize_doc(data) for data in grouped_results]
        for result in response_results:
            result['display_text'] = result.get('manual_text') or result.get('extracted_text')
        
        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {'status': 'completed', 'updated_at': datetime.utcnow()}}
        )
        
        # Include grouping info in response
        total_merged = sum(info['merged_count'] for info in merge_info.values())
        message = f'OCR completed for {len(response_results)} unique items'
        if len(deleted_ids) > 0:
            message += f' ({total_merged} original detections grouped)'
        
        return jsonify({
            'message': message,
            'results': response_results,
            'grouping_info': {
                'total_unique': len(response_results),
                'total_original': len(results),
                'merged_count': len(deleted_ids)
            }
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
    shape_type = data.get('shape_type', 'manual')
    shape_data = data.get('shape_data')
    
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
            label_mode=True,
            capture_adjacent=False
        )
        
        # Search for multiplier in nearby regions
        quantity = ocr_service.find_multiplier_near_region(
            floorplan['image_filepath'],
            int(x), int(y), int(width), int(height)
        )
        
        # Log for debugging
        current_app.logger.info(f"Manual OCR - Text: '{text}' | Quantity: {quantity}")
        
        # Get next shape index
        max_doc = mongo.db.extracted_data.find_one(
            {'floorplan_id': ObjectId(floorplan_id)},
            sort=[('shape_index', -1)]
        )
        next_index = (max_doc['shape_index'] + 1) if max_doc else 0
        
        # Create new extracted data record
        doc = create_extracted_data_doc(
            shape_index=next_index,
            shape_type=shape_type,
            x=int(x),
            y=int(y),
            width=int(width),
            height=int(height),
            floorplan_id=floorplan_id,
            shape_data=shape_data
        )
        doc['extracted_text'] = text
        doc['confidence'] = confidence
        doc['quantity'] = quantity
        doc['is_manual'] = True
        doc['detection_method'] = 'manual'
        
        result = mongo.db.extracted_data.insert_one(doc)
        doc['_id'] = result.inserted_id
        doc['display_text'] = text
        
        # Auto-save as shape template for self-learning
        template_id = None
        try:
            import cv2
            img = cv2.imread(floorplan['image_filepath'])
            if img is not None:
                ix, iy = int(x), int(y)
                iw, ih = int(width), int(height)
                img_h, img_w = img.shape[:2]
                ix = max(0, ix)
                iy = max(0, iy)
                iw = min(iw, img_w - ix)
                ih = min(ih, img_h - iy)

                if iw > 10 and ih > 10:
                    cropped = img[iy:iy+ih, ix:ix+iw]

                    cv_service = CVService()
                    color_profile = cv_service.extract_color_profile(cropped)

                    tmpl_doc = create_shape_template_doc(
                        shape_type=shape_type,
                        image_path='',  # placeholder, set after insert
                        width=iw,
                        height=ih,
                        color_profile=color_profile,
                        source_floorplan_id=floorplan_id,
                        extracted_text=text,
                        created_by=user_id
                    )
                    tmpl_result = mongo.db.shape_templates.insert_one(tmpl_doc)
                    template_id = str(tmpl_result.inserted_id)

                    templates_folder = current_app.config['SHAPE_TEMPLATES_FOLDER']
                    tmpl_path = os.path.join(templates_folder, f'{template_id}.png')
                    cv2.imwrite(tmpl_path, cropped)

                    mongo.db.shape_templates.update_one(
                        {'_id': tmpl_result.inserted_id},
                        {'$set': {'image_path': tmpl_path}}
                    )
                    current_app.logger.info(f"Saved shape template {template_id} from manual correction")
        except Exception as tmpl_err:
            current_app.logger.warning(f"Failed to save shape template: {tmpl_err}")
        
        response_data = {
            'message': 'Text extracted successfully',
            'result': serialize_doc(doc)
        }
        if template_id:
            response_data['template_id'] = template_id
            response_data['template_saved'] = True

        return jsonify(response_data), 200
        
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
    
    # Allow manual update of quantity
    if 'quantity' in data:
        update_fields['quantity'] = int(data['quantity'])
    
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


@processing_bp.route('/templates', methods=['GET'])
@jwt_required()
def list_shape_templates():
    """List all shape templates used for self-learning detection."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    shape_type_filter = request.args.get('shape_type')
    active_only = request.args.get('active_only', 'true').lower() == 'true'

    query = {}
    if active_only:
        query['is_active'] = True
    if shape_type_filter:
        query['shape_type'] = shape_type_filter

    total = mongo.db.shape_templates.count_documents(query)
    templates = list(
        mongo.db.shape_templates.find(query)
        .sort('created_at', -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )

    return jsonify({
        'templates': [shape_template_to_dict(t) for t in templates],
        'total': total,
        'page': page,
        'per_page': per_page
    }), 200


@processing_bp.route('/templates/<template_id>', methods=['PUT'])
@jwt_required()
def update_shape_template(template_id):
    """Toggle a shape template active/inactive."""
    try:
        tmpl = mongo.db.shape_templates.find_one({'_id': ObjectId(template_id)})
    except Exception:
        return jsonify({'error': 'Invalid template ID'}), 400

    if not tmpl:
        return jsonify({'error': 'Template not found'}), 404

    data = request.get_json() or {}
    update_fields = {}

    if 'is_active' in data:
        update_fields['is_active'] = bool(data['is_active'])

    if not update_fields:
        return jsonify({'error': 'No valid fields to update'}), 400

    mongo.db.shape_templates.update_one(
        {'_id': ObjectId(template_id)},
        {'$set': update_fields}
    )

    updated = mongo.db.shape_templates.find_one({'_id': ObjectId(template_id)})
    return jsonify({
        'message': 'Template updated',
        'template': shape_template_to_dict(updated)
    }), 200


@processing_bp.route('/templates/<template_id>', methods=['DELETE'])
@jwt_required()
def delete_shape_template(template_id):
    """Soft-delete a shape template (set is_active to False)."""
    try:
        tmpl = mongo.db.shape_templates.find_one({'_id': ObjectId(template_id)})
    except Exception:
        return jsonify({'error': 'Invalid template ID'}), 400

    if not tmpl:
        return jsonify({'error': 'Template not found'}), 404

    mongo.db.shape_templates.update_one(
        {'_id': ObjectId(template_id)},
        {'$set': {'is_active': False}}
    )

    return jsonify({'message': 'Template deactivated'}), 200


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


@processing_bp.route('/image/<floorplan_id>/preview', methods=['GET'])
@jwt_required()
def get_floorplan_preview(floorplan_id):
    """Get the low-resolution preview of a floorplan image."""
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

    preview_path = floorplan.get('preview_filepath', '')
    if preview_path and os.path.exists(preview_path):
        return send_file(preview_path, mimetype='image/png')

    if not os.path.exists(floorplan.get('image_filepath', '')):
        return jsonify({'error': 'Image not found'}), 404

    return send_file(floorplan['image_filepath'], mimetype='image/png')


@processing_bp.route('/split/<floorplan_id>', methods=['POST'])
@jwt_required()
def split_floorplan(floorplan_id):
    """Split a floorplan into multiple floors by cropping regions.
    
    Request body:
    {
        "regions": [
            {"x": 0, "y": 0, "width": 500, "height": 600, "name": "Floor 1"},
            {"x": 0, "y": 600, "width": 500, "height": 600, "name": "Floor 2"}
        ],
        "delete_original": false  // optional, defaults to false
    }
    """
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
    if not data or 'regions' not in data:
        return jsonify({'error': 'Crop regions are required'}), 400
    
    regions = data['regions']
    delete_original = data.get('delete_original', False)
    
    if not isinstance(regions, list) or len(regions) < 1:
        return jsonify({'error': 'At least one crop region is required'}), 400
    
    # Validate each region
    for i, region in enumerate(regions):
        if not all(key in region for key in ['x', 'y', 'width', 'height']):
            return jsonify({'error': f'Region {i + 1} missing required fields (x, y, width, height)'}), 400
        if region['width'] <= 0 or region['height'] <= 0:
            return jsonify({'error': f'Region {i + 1} has invalid dimensions'}), 400
    
    if not os.path.exists(floorplan.get('image_filepath', '')):
        return jsonify({'error': 'Floorplan image not found'}), 404
    
    try:
        cv_service = CVService()
        project_id = str(floorplan['project_id'])
        
        # Create output directory for cropped images
        image_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'images', project_id)
        os.makedirs(image_dir, exist_ok=True)
        
        # Crop the image into regions
        cropped_images = cv_service.crop_image(
            floorplan['image_filepath'],
            regions,
            image_dir
        )
        
        if not cropped_images:
            return jsonify({'error': 'No valid regions were cropped'}), 400
        
        # Get current max floor number
        max_floor = mongo.db.floorplans.find_one(
            {'project_id': floorplan['project_id']},
            sort=[('floor_number', -1)]
        )
        next_floor_number = (max_floor['floor_number'] + 1) if max_floor else 1
        
        # Create new floorplan documents for each cropped image
        new_floorplans = []
        for idx, crop_info in enumerate(cropped_images):
            floor_name = crop_info['name']
            
            floorplan_doc = create_floorplan_doc(
                floor_number=next_floor_number + idx,
                floor_name=floor_name,
                pdf_filename=floorplan.get('pdf_filename', ''),
                pdf_filepath=floorplan.get('pdf_filepath', ''),
                image_filepath=crop_info['path'],
                project_id=project_id
            )
            
            # Add metadata about the crop source
            floorplan_doc['cropped_from'] = floorplan_id
            floorplan_doc['crop_region'] = {
                'x': crop_info['x'],
                'y': crop_info['y'],
                'width': crop_info['width'],
                'height': crop_info['height']
            }
            
            result = mongo.db.floorplans.insert_one(floorplan_doc)
            floorplan_doc['_id'] = result.inserted_id
            
            fp_dict = serialize_doc(floorplan_doc)
            fp_dict['data_count'] = 0
            fp_dict['extracted_data'] = []
            new_floorplans.append(fp_dict)
        
        # Optionally delete the original floorplan
        if delete_original:
            # Delete extracted data for original floorplan
            mongo.db.extracted_data.delete_many({'floorplan_id': ObjectId(floorplan_id)})
            
            # Delete original floorplan image (optional - keep for reference)
            # if os.path.exists(floorplan['image_filepath']):
            #     os.remove(floorplan['image_filepath'])
            
            # Delete the floorplan document
            mongo.db.floorplans.delete_one({'_id': ObjectId(floorplan_id)})
        
        # Update project timestamp
        mongo.db.projects.update_one(
            {'_id': ObjectId(project_id)},
            {'$set': {'updated_at': datetime.utcnow()}}
        )
        
        return jsonify({
            'message': f'Successfully split floorplan into {len(new_floorplans)} floors',
            'floorplans': new_floorplans,
            'original_deleted': delete_original
        }), 201
        
    except Exception as e:
        current_app.logger.error(f'Failed to split floorplan: {str(e)}')
        return jsonify({'error': f'Failed to split floorplan: {str(e)}'}), 500


@processing_bp.route('/image-dimensions/<floorplan_id>', methods=['GET'])
@jwt_required()
def get_image_dimensions(floorplan_id):
    """Get the dimensions of a floorplan image."""
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
    
    try:
        cv_service = CVService()
        width, height = cv_service.get_image_dimensions(floorplan['image_filepath'])
        
        return jsonify({
            'width': width,
            'height': height
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to get image dimensions: {str(e)}'}), 500


@processing_bp.route('/batch-upload/<project_id>', methods=['POST'])
@jwt_required()
@require_project_modify
def batch_upload_floorplans(project_id, _user=None, _project=None):
    """Upload multiple PDF floorplans with automatic shape detection and OCR.
    
    Files are processed in the background. Returns a job ID for status polling.
    """
    user_id = get_jwt_identity()
    
    if 'files' not in request.files:
        return jsonify({'error': 'No files provided'}), 400
    
    files = request.files.getlist('files')
    
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'No files selected'}), 400
    
    # Validate all files are PDFs
    valid_files = []
    for file in files:
        if file.filename and allowed_file(file.filename, {'pdf'}):
            valid_files.append(file)
    
    if not valid_files:
        return jsonify({'error': 'No valid PDF files provided'}), 400
    
    # Create PDF directory
    pdf_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'pdfs', project_id)
    os.makedirs(pdf_dir, exist_ok=True)
    
    # Save files and prepare job
    files_info = []
    job_files = []
    
    for idx, file in enumerate(valid_files):
        filename = secure_filename(file.filename)
        filepath = os.path.join(pdf_dir, filename)
        
        # Handle duplicate filenames
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(filepath):
            filename = f"{base}_{counter}{ext}"
            filepath = os.path.join(pdf_dir, filename)
            counter += 1
        
        file.save(filepath)
        
        files_info.append({
            'index': idx,
            'filename': filename,
            'file_path': filepath
        })
        job_files.append(create_processing_file_doc(filename))
    
    # Create job document
    job_doc = create_processing_job_doc(project_id, user_id, job_files)
    result = mongo.db.processing_jobs.insert_one(job_doc)
    job_doc['_id'] = result.inserted_id
    
    # Get detection method from form data (default: 'auto')
    # Options: 'auto' (auto-detect), 'rectangle' (red rectangles), or 'circle' (template-based circle detection)
    detection_method = request.form.get('detection_method', 'auto')
    
    # Extract config values needed for processing
    config = {
        'TITLE_REGION_X_START': current_app.config.get('TITLE_REGION_X_START', 60),
        'TITLE_REGION_Y_START': current_app.config.get('TITLE_REGION_Y_START', 85),
        'TITLE_REGION_WIDTH': current_app.config.get('TITLE_REGION_WIDTH', 40),
        'TITLE_REGION_HEIGHT': current_app.config.get('TITLE_REGION_HEIGHT', 15),
        'detection_method': detection_method
    }
    
    # Start background processing
    start_batch_processing(
        job_id=job_doc['job_id'],
        files_info=files_info,
        project_id=project_id,
        upload_folder=current_app.config['UPLOAD_FOLDER'],
        config=config
    )
    
    return jsonify({
        'message': f'Started processing {len(valid_files)} PDF files',
        'job': processing_job_to_dict(job_doc)
    }), 202


@processing_bp.route('/batch-upload/<project_id>/status', methods=['GET'])
@jwt_required()
@require_project_access
def get_batch_upload_status(project_id, _user=None, _project=None):
    """Get the status of the current batch upload job for a project."""
    
    # Get the most recent job for this project
    job = mongo.db.processing_jobs.find_one(
        {'project_id': ObjectId(project_id)},
        sort=[('created_at', -1)]
    )
    
    if not job:
        return jsonify({'error': 'No batch upload job found'}), 404
    
    return jsonify({
        'job': processing_job_to_dict(job)
    }), 200


@processing_bp.route('/batch-upload/<project_id>/job/<job_id>', methods=['GET'])
@jwt_required()
@require_project_access
def get_batch_job_status(project_id, job_id, _user=None, _project=None):
    """Get the status of a specific batch upload job."""
    
    job = mongo.db.processing_jobs.find_one({
        'job_id': job_id,
        'project_id': ObjectId(project_id)
    })
    
    if not job:
        return jsonify({'error': 'Batch upload job not found'}), 404
    
    return jsonify({
        'job': processing_job_to_dict(job)
    }), 200
