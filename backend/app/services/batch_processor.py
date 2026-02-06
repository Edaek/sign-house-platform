"""Background batch processor for PDF upload with auto shape detection and OCR."""

import os
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from bson import ObjectId

from app import mongo
from app.models import create_floorplan_doc, create_extracted_data_doc, serialize_doc
from app.services.pdf_service import PDFService
from app.services.cv_service import CVService
from app.services.ocr_service import OCRService

logger = logging.getLogger(__name__)

# Thread pool for background processing
executor = ThreadPoolExecutor(max_workers=2)


def update_job_status(job_id, updates):
    """Update job status in MongoDB."""
    updates['updated_at'] = datetime.utcnow()
    mongo.db.processing_jobs.update_one(
        {'job_id': job_id},
        {'$set': updates}
    )


def update_file_status(job_id, file_index, updates):
    """Update a specific file's status in the job."""
    update_fields = {f'files.{file_index}.{k}': v for k, v in updates.items()}
    update_fields['updated_at'] = datetime.utcnow()
    mongo.db.processing_jobs.update_one(
        {'job_id': job_id},
        {'$set': update_fields}
    )


def process_single_pdf(job_id, file_index, file_path, filename, project_id, upload_folder, config):
    """Process a single PDF file: convert, detect shapes, run OCR.
    
    Args:
        job_id: The batch job ID
        file_index: Index of this file in the job's files array
        file_path: Path to the saved PDF file
        filename: Original filename
        project_id: Project ID to associate floorplans with
        upload_folder: Base upload folder path
        config: App config dict with title extraction settings
    """
    try:
        # Update status to converting
        update_file_status(job_id, file_index, {
            'status': 'converting',
            'progress': 10,
            'started_at': datetime.utcnow().isoformat()
        })
        
        # Convert PDF to images
        pdf_service = PDFService()
        image_dir = os.path.join(upload_folder, 'images', project_id)
        os.makedirs(image_dir, exist_ok=True)
        
        pages = pdf_service.convert_to_images(file_path, image_dir)
        
        update_file_status(job_id, file_index, {
            'status': 'converting',
            'progress': 20,
            'pages_total': len(pages)
        })
        
        # Initialize services
        cv_service = CVService()
        ocr_service = None
        try:
            ocr_service = OCRService()
        except Exception as e:
            logger.warning(f"Failed to initialize OCR service: {str(e)}")
        
        floorplan_ids = []
        total_shapes_detected = 0
        
        # Process each page
        for page_idx, page_info in enumerate(pages):
            page_progress = 20 + (page_idx / len(pages)) * 60  # Progress from 20% to 80%
            
            # Extract title from floorplan
            extracted_title = None
            if ocr_service:
                try:
                    extracted_title = ocr_service.extract_title_from_floorplan(
                        page_info['image_path'],
                        x_start_pct=config.get('TITLE_REGION_X_START', 60),
                        y_start_pct=config.get('TITLE_REGION_Y_START', 85),
                        width_pct=config.get('TITLE_REGION_WIDTH', 40),
                        height_pct=config.get('TITLE_REGION_HEIGHT', 15)
                    )
                except Exception as e:
                    logger.warning(f"Failed to extract title for page {page_info['page_number']}: {str(e)}")
            
            floor_name = extracted_title if extracted_title else f"Floor {page_info['page_number']}"
            
            # Create floorplan document
            floorplan_doc = create_floorplan_doc(
                floor_number=page_info['page_number'],
                floor_name=floor_name,
                pdf_filename=filename,
                pdf_filepath=file_path,
                image_filepath=page_info['image_path'],
                project_id=project_id
            )
            result = mongo.db.floorplans.insert_one(floorplan_doc)
            floorplan_id = str(result.inserted_id)
            floorplan_ids.append(floorplan_id)
            
            # Update progress - detecting shapes
            update_file_status(job_id, file_index, {
                'status': 'detecting',
                'progress': int(page_progress + 10),
                'pages_processed': page_idx + 1
            })
            
            # Detect shapes - use detection_method from config (default: 'auto')
            detection_method = config.get('detection_method', 'auto')
            try:
                # Auto-detect: check if there's a sample circle in upper-right corner
                if detection_method == 'auto':
                    if cv_service.has_sample_circle(page_info['image_path']):
                        detection_method = 'circle'
                        logger.info(f"Auto-detected circle markers on page {page_info['page_number']}")
                    else:
                        detection_method = 'rectangle'
                        logger.info(f"Auto-detected rectangle markers on page {page_info['page_number']}")
                
                if detection_method == 'circle':
                    # Use template-based circle detection
                    shapes = cv_service.detect_circles_by_template(page_info['image_path'])
                    shape_type = 'circle'
                else:
                    # Use red rectangle detection (default)
                    shapes = cv_service.detect_red_rectangles(page_info['image_path'])
                    shape_type = 'rectangle'
                
                # Update floorplan with shape type
                mongo.db.floorplans.update_one(
                    {'_id': ObjectId(floorplan_id)},
                    {'$set': {
                        'shape_type': shape_type,
                        'status': 'processing',
                        'updated_at': datetime.utcnow()
                    }}
                )
                
                # Create extracted data records
                for idx, shape in enumerate(shapes):
                    shape_data = None
                    if 'radius' in shape:
                        shape_data = {
                            'radius': shape['radius'],
                            'center_x': shape['center_x'],
                            'center_y': shape['center_y']
                        }
                        # Include confidence score if available (from template matching)
                        if 'confidence' in shape:
                            shape_data['confidence'] = shape['confidence']
                    
                    doc = create_extracted_data_doc(
                        shape_index=idx,
                        shape_type=shape_type,
                        x=shape['x'],
                        y=shape['y'],
                        width=shape['width'],
                        height=shape['height'],
                        floorplan_id=floorplan_id,
                        shape_data=shape_data
                    )
                    mongo.db.extracted_data.insert_one(doc)
                
                total_shapes_detected += len(shapes)
                
                # Update progress - running OCR
                update_file_status(job_id, file_index, {
                    'status': 'ocr',
                    'progress': int(page_progress + 20),
                    'shapes_detected': total_shapes_detected
                })
                
                # Run OCR on detected shapes
                if ocr_service and shapes:
                    extracted_data = list(mongo.db.extracted_data.find({'floorplan_id': ObjectId(floorplan_id)}))
                    
                    for data in extracted_data:
                        try:
                            text, confidence = ocr_service.extract_text_from_region(
                                page_info['image_path'],
                                data['x'], data['y'], data['width'], data['height'],
                                padding=0,
                                label_mode=True,
                                capture_adjacent=False
                            )
                            
                            quantity = ocr_service.find_multiplier_near_region(
                                page_info['image_path'],
                                data['x'], data['y'], data['width'], data['height']
                            )
                            
                            mongo.db.extracted_data.update_one(
                                {'_id': data['_id']},
                                {'$set': {
                                    'extracted_text': text,
                                    'confidence': confidence,
                                    'quantity': quantity,
                                    'updated_at': datetime.utcnow()
                                }}
                            )
                        except Exception as e:
                            logger.warning(f"OCR failed for shape {data['_id']}: {str(e)}")
                    
                    # Group OCR results
                    extracted_data = list(mongo.db.extracted_data.find({'floorplan_id': ObjectId(floorplan_id)}))
                    grouping_result = ocr_service.group_ocr_results([serialize_doc(d) for d in extracted_data])
                    
                    # Update grouped records and delete duplicates
                    for result_item in grouping_result['grouped']:
                        result_id = result_item['_id']
                        if str(result_id) in grouping_result['merge_info']:
                            info = grouping_result['merge_info'][str(result_id)]
                            mongo.db.extracted_data.update_one(
                                {'_id': ObjectId(result_id) if isinstance(result_id, str) else result_id},
                                {'$set': {
                                    'quantity': info['total_quantity'],
                                    'merged_count': info['merged_count'],
                                    'original_shape_indices': info['original_indices'],
                                    'all_bounding_boxes': info['all_bounding_boxes'],
                                    'updated_at': datetime.utcnow()
                                }}
                            )
                    
                    if grouping_result['deleted_ids']:
                        mongo.db.extracted_data.delete_many({
                            '_id': {'$in': [ObjectId(id) if isinstance(id, str) else id for id in grouping_result['deleted_ids']]}
                        })
                
                # Mark floorplan as completed
                mongo.db.floorplans.update_one(
                    {'_id': ObjectId(floorplan_id)},
                    {'$set': {'status': 'completed', 'updated_at': datetime.utcnow()}}
                )
                
            except Exception as e:
                logger.error(f"Shape detection/OCR failed for floorplan {floorplan_id}: {str(e)}")
                mongo.db.floorplans.update_one(
                    {'_id': ObjectId(floorplan_id)},
                    {'$set': {'status': 'pending', 'updated_at': datetime.utcnow()}}
                )
        
        # File completed successfully
        update_file_status(job_id, file_index, {
            'status': 'completed',
            'progress': 100,
            'floorplan_ids': floorplan_ids,
            'shapes_detected': total_shapes_detected,
            'completed_at': datetime.utcnow().isoformat()
        })
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to process PDF {filename}: {str(e)}")
        update_file_status(job_id, file_index, {
            'status': 'error',
            'error': str(e),
            'completed_at': datetime.utcnow().isoformat()
        })
        return False


def process_batch_job(job_id, files_info, project_id, upload_folder, config):
    """Process all files in a batch job.
    
    Args:
        job_id: The batch job ID
        files_info: List of dicts with 'file_path', 'filename', 'index'
        project_id: Project ID
        upload_folder: Base upload folder path
        config: App config dict
    """
    try:
        update_job_status(job_id, {'status': 'processing'})
        
        processed_count = 0
        error_count = 0
        
        for file_info in files_info:
            success = process_single_pdf(
                job_id=job_id,
                file_index=file_info['index'],
                file_path=file_info['file_path'],
                filename=file_info['filename'],
                project_id=project_id,
                upload_folder=upload_folder,
                config=config
            )
            
            if success:
                processed_count += 1
            else:
                error_count += 1
            
            # Update overall job progress
            update_job_status(job_id, {
                'processed_files': processed_count + error_count
            })
        
        # Mark job as completed
        final_status = 'completed' if error_count == 0 else ('error' if processed_count == 0 else 'completed')
        update_job_status(job_id, {
            'status': final_status,
            'processed_files': processed_count + error_count,
            'completed_at': datetime.utcnow()
        })
        
        # Update project status
        mongo.db.projects.update_one(
            {'_id': ObjectId(project_id)},
            {'$set': {'status': 'in_progress', 'updated_at': datetime.utcnow()}}
        )
        
        logger.info(f"Batch job {job_id} completed: {processed_count} succeeded, {error_count} failed")
        
    except Exception as e:
        logger.error(f"Batch job {job_id} failed: {str(e)}")
        update_job_status(job_id, {
            'status': 'error',
            'completed_at': datetime.utcnow()
        })


def start_batch_processing(job_id, files_info, project_id, upload_folder, config):
    """Start batch processing in a background thread.
    
    Args:
        job_id: The batch job ID
        files_info: List of dicts with 'file_path', 'filename', 'index'
        project_id: Project ID
        upload_folder: Base upload folder path
        config: App config dict (must be serializable - extract needed values)
    """
    executor.submit(
        process_batch_job,
        job_id,
        files_info,
        project_id,
        upload_folder,
        config
    )

