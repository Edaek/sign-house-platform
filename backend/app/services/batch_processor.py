"""Background batch processor for PDF upload with auto shape detection and OCR."""

import os
import logging
import time as _time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from bson import ObjectId

import cv2

from app import mongo
from app.models import create_floorplan_doc, create_extracted_data_doc, serialize_doc
from app.services.pdf_service import PDFService
from app.services.cv_service import CVService
from app.services.ocr_service import OCRService, is_valid_sign_code, clean_ocr_text

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


def process_single_pdf(job_id, file_index, file_path, filename, project_id, upload_folder, config, detection_mode='accurate'):
    """Process a single PDF file: convert, detect shapes, run OCR.
    
    Args:
        job_id: The batch job ID
        file_index: Index of this file in the job's files array
        file_path: Path to the saved PDF file
        filename: Original filename
        project_id: Project ID to associate floorplans with
        upload_folder: Base upload folder path
        config: App config dict with title extraction settings
        detection_mode: 'fast' or 'accurate'
    """
    try:
        # Update status to converting
        update_file_status(job_id, file_index, {
            'status': 'converting',
            'progress': 10,
            'started_at': datetime.utcnow().isoformat()
        })
        
        # Convert PDF to images
        pdf_service = PDFService(dpi=config.get('PDF_DPI', 200))
        image_dir = os.path.join(upload_folder, 'images', project_id)
        os.makedirs(image_dir, exist_ok=True)
        
        pages = pdf_service.convert_to_images(
            file_path, image_dir, preview_dpi=config.get('PDF_PREVIEW_DPI', 150)
        )
        
        update_file_status(job_id, file_index, {
            'status': 'converting',
            'progress': 20,
            'pages_total': len(pages)
        })
        
        # Initialize services
        cv_service = CVService(mode=detection_mode)
        ocr_service = None
        try:
            ocr_service = OCRService()
        except Exception as e:
            logger.warning(f"Failed to initialize OCR service: {str(e)}")
        
        floorplan_ids = []
        total_shapes_detected = 0
        
        # Query learned templates once for all pages (avoid N identical DB queries)
        active_templates = []
        try:
            active_templates = list(mongo.db.shape_templates.find({'is_active': True}))
        except Exception as e:
            logger.warning(f"Failed to load learned templates: {e}")
        
        # Process each page
        for page_idx, page_info in enumerate(pages):
            page_progress = 20 + (page_idx / len(pages)) * 60  # Progress from 20% to 80%
            page_t0 = _time.time()
            
            # Load image once for this page — shared across detection, OCR, etc.
            page_img = cv2.imread(page_info['image_path'])
            if page_img is None:
                logger.error(f"Could not load page image: {page_info['image_path']}")
                continue
            
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
            floorplan_doc['preview_filepath'] = page_info.get('preview_path', '')
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
                
                detect_t0 = _time.time()
                if detection_method == 'circle':
                    shapes = cv_service.detect_circles_by_template(page_info['image_path'])
                    shape_type = 'circle'
                else:
                    shapes = cv_service.detect_red_rectangles(page_info['image_path'])
                    shape_type = 'rectangle'
                logger.info(f"Page {page_info['page_number']}: primary detection ({shape_type}) "
                            f"found {len(shapes)} shapes in {_time.time() - detect_t0:.2f}s")
                
                # Learned template matching pass (skipped in fast mode)
                if detection_mode != 'fast':
                    try:
                        if active_templates:
                            learn_t0 = _time.time()
                            raw_learned = cv_service.detect_from_learned_templates(
                                page_info['image_path'], active_templates,
                                shape_type=shape_type, img=page_img
                            )
                            learned_unique = cv_service.deduplicate_with_existing(raw_learned, shapes)
                            learn_elapsed = _time.time() - learn_t0
                            if learned_unique:
                                logger.info(f"Page {page_info['page_number']}: learned templates added "
                                            f"{len(learned_unique)} shapes in {learn_elapsed:.2f}s")
                                shapes = shapes + learned_unique
                            else:
                                logger.info(f"Page {page_info['page_number']}: learned templates "
                                            f"added 0 shapes in {learn_elapsed:.2f}s")
                    except Exception as tmpl_err:
                        logger.warning(f"Batch: learned template matching failed: {tmpl_err}")
                
                mongo.db.floorplans.update_one(
                    {'_id': ObjectId(floorplan_id)},
                    {'$set': {
                        'shape_type': shape_type,
                        'status': 'processing',
                        'updated_at': datetime.utcnow()
                    }}
                )
                
                total_shapes_detected += len(shapes)
                
                update_file_status(job_id, file_index, {
                    'status': 'ocr',
                    'progress': int(page_progress + 20),
                    'shapes_detected': total_shapes_detected
                })
                
                # Merged OCR + sign-code filter + save (reuse pre-loaded image)
                is_circle = shape_type == 'circle'
                ocr_results = []
                
                if ocr_service:
                    ocr_t0 = _time.time()
                    for idx, shape in enumerate(shapes):
                        try:
                            cv_text = shape.get('extracted_text', '')
                            cv_conf = shape.get('ocr_confidence', 0.0)

                            if cv_text and is_valid_sign_code(cv_text):
                                cleaned = cv_text
                                confidence = cv_conf
                            else:
                                if is_circle and shape.get('center_x') is not None:
                                    text, confidence = ocr_service.extract_text_from_circle(
                                        page_info['image_path'],
                                        shape['center_x'], shape['center_y'],
                                        shape['radius'], padding=10,
                                        img=page_img
                                    )
                                else:
                                    text, confidence = ocr_service.extract_text_from_region(
                                        page_info['image_path'],
                                        shape['x'], shape['y'],
                                        shape['width'], shape['height'],
                                        padding=0, label_mode=True, capture_adjacent=False,
                                        img=page_img
                                    )
                                cleaned = clean_ocr_text(text)
                                if not is_valid_sign_code(cleaned):
                                    continue

                            if detection_mode == 'fast':
                                quantity = 1
                            else:
                                quantity = ocr_service.find_multiplier_near_region(
                                    page_info['image_path'],
                                    shape['x'], shape['y'],
                                    shape['width'], shape['height'],
                                    img=page_img
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
                                shape_type=shape_type,
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
                            
                            result_insert = mongo.db.extracted_data.insert_one(doc)
                            doc['_id'] = result_insert.inserted_id
                            ocr_results.append(doc)
                        except Exception as e:
                            logger.warning(f"OCR failed for shape idx {idx}: {str(e)}")
                    
                    logger.info(f"Page {page_info['page_number']}: OCR processed "
                                f"{len(shapes)} shapes → {len(ocr_results)} valid in "
                                f"{_time.time() - ocr_t0:.2f}s")
                
                # Mark floorplan as completed
                mongo.db.floorplans.update_one(
                    {'_id': ObjectId(floorplan_id)},
                    {'$set': {'status': 'completed', 'updated_at': datetime.utcnow()}}
                )
                
                logger.info(f"Page {page_info['page_number']}: total page time {_time.time() - page_t0:.2f}s")
                
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


def process_batch_job(job_id, files_info, project_id, upload_folder, config, detection_mode='accurate'):
    """Process all files in a batch job.
    
    Args:
        job_id: The batch job ID
        files_info: List of dicts with 'file_path', 'filename', 'index'
        project_id: Project ID
        upload_folder: Base upload folder path
        config: App config dict
        detection_mode: 'fast' or 'accurate'
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
                config=config,
                detection_mode=detection_mode
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


def start_batch_processing(job_id, files_info, project_id, upload_folder, config, detection_mode='accurate'):
    """Start batch processing in a background thread.
    
    Args:
        job_id: The batch job ID
        files_info: List of dicts with 'file_path', 'filename', 'index'
        project_id: Project ID
        upload_folder: Base upload folder path
        config: App config dict (must be serializable - extract needed values)
        detection_mode: 'fast' or 'accurate'
    """
    executor.submit(
        process_batch_job,
        job_id,
        files_info,
        project_id,
        upload_folder,
        config,
        detection_mode
    )

