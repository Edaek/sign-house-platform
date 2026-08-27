"""Background batch processor for PDF upload with auto shape detection and OCR."""

import os
import logging
import time as _time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from bson import ObjectId

import cv2

from app import mongo
from app.models import create_floorplan_doc, create_extracted_data_doc, create_processing_file_doc
from app.services.pdf_service import PDFService
from app.services.cv_service import CVService
from app.services.ocr_service import OCRService, is_valid_sign_code, clean_ocr_text
from app.services.job_cancel import (
    is_cancel_requested,
    is_file_cancel_requested,
    cancel_remaining_batch_files,
    finalize_cancelled,
    make_cancel_checker,
    JobCancelledError,
)

logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=2)


def update_job_status(job_id, updates):
    updates['updated_at'] = datetime.utcnow()
    mongo.db.processing_jobs.update_one({'job_id': job_id}, {'$set': updates})


def update_file_status(job_id, file_index, updates):
    update_fields = {f'files.{file_index}.{k}': v for k, v in updates.items()}
    update_fields['updated_at'] = datetime.utcnow()
    mongo.db.processing_jobs.update_one({'job_id': job_id}, {'$set': update_fields})


def _reserve_floor_numbers(project_id, count):
    max_doc = mongo.db.floorplans.find_one(
        {'project_id': ObjectId(project_id)},
        sort=[('floor_number', -1)],
    )
    start = (max_doc['floor_number'] + 1) if max_doc else 1
    return list(range(start, start + count))


def _mark_file_cancelled(job_id, file_index, *, pages_processed=0, floorplan_ids=None,
                         shapes_detected=0):
    updates = {
        'status': 'cancelled',
        'cancel_requested': True,
        'error': 'Cancelled by user',
        'completed_at': datetime.utcnow().isoformat(),
    }
    if pages_processed:
        updates['pages_processed'] = pages_processed
    if floorplan_ids is not None:
        updates['floorplan_ids'] = floorplan_ids
    if shapes_detected:
        updates['shapes_detected'] = shapes_detected
    update_file_status(job_id, file_index, updates)


def _finalize_batch_cancel(job_id, from_file_index):
    cancel_remaining_batch_files(job_id, from_file_index)
    finalize_cancelled(job_id)


def ingest_pdf_pages(job_id, file_index, file_path, filename, project_id, upload_folder,
                     config, ocr_service=None):
    """Phase 1: convert PDF to images and create pending floorplan records for every page."""
    if is_cancel_requested(job_id):
        _mark_file_cancelled(job_id, file_index)
        return None, 'cancelled'

    if is_file_cancel_requested(job_id, file_index):
        return None, 'file_cancelled'

    should_cancel = make_cancel_checker(job_id, file_index)

    try:
        update_file_status(job_id, file_index, {
            'status': 'converting',
            'progress': 5,
            'started_at': datetime.utcnow().isoformat(),
        })

        pdf_service = PDFService(dpi=config.get('PDF_DPI', 200))
        image_dir = os.path.join(upload_folder, 'images', project_id)
        os.makedirs(image_dir, exist_ok=True)

        pages = pdf_service.convert_to_images(
            file_path, image_dir,
            preview_dpi=config.get('PDF_PREVIEW_DPI', 150),
            should_cancel=should_cancel,
        )

        floor_numbers = _reserve_floor_numbers(project_id, len(pages))
        floorplan_ids = []
        page_items = []

        for page_idx, (page_info, floor_number) in enumerate(zip(pages, floor_numbers)):
            if is_cancel_requested(job_id):
                update_file_status(job_id, file_index, {
                    'status': 'cancelled',
                    'cancel_requested': True,
                    'error': 'Cancelled by user',
                    'pages_total': len(pages),
                    'pages_processed': page_idx,
                    'floorplan_ids': floorplan_ids,
                    'completed_at': datetime.utcnow().isoformat(),
                })
                return page_items, 'cancelled'

            if is_file_cancel_requested(job_id, file_index):
                update_file_status(job_id, file_index, {
                    'status': 'cancelled',
                    'cancel_requested': True,
                    'error': 'Cancelled by user',
                    'pages_total': len(pages),
                    'pages_processed': page_idx,
                    'floorplan_ids': floorplan_ids,
                    'completed_at': datetime.utcnow().isoformat(),
                })
                return page_items, 'file_cancelled'

            extracted_title = None
            if ocr_service:
                try:
                    extracted_title = ocr_service.extract_title_from_floorplan(
                        page_info['image_path'],
                        x_start_pct=config.get('TITLE_REGION_X_START', 60),
                        y_start_pct=config.get('TITLE_REGION_Y_START', 85),
                        width_pct=config.get('TITLE_REGION_WIDTH', 40),
                        height_pct=config.get('TITLE_REGION_HEIGHT', 15),
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to extract title for {filename} page {page_info['page_number']}: {e}"
                    )

            floor_name = extracted_title or f"Floor {page_info['page_number']}"
            if len(pages) > 1:
                base = os.path.splitext(filename)[0]
                floor_name = f"{base} — {floor_name}"

            floorplan_doc = create_floorplan_doc(
                floor_number=floor_number,
                floor_name=floor_name,
                pdf_filename=filename,
                pdf_filepath=file_path,
                image_filepath=page_info['image_path'],
                project_id=project_id,
            )
            floorplan_doc['preview_filepath'] = page_info.get('preview_path', '')
            result = mongo.db.floorplans.insert_one(floorplan_doc)
            floorplan_id = str(result.inserted_id)
            floorplan_ids.append(floorplan_id)

            page_items.append({
                'file_index': file_index,
                'filename': filename,
                'file_path': file_path,
                'floorplan_id': floorplan_id,
                'page_info': page_info,
                'page_idx': page_idx,
                'pages_total': len(pages),
            })

        update_file_status(job_id, file_index, {
            'status': 'pending',
            'progress': 25,
            'pages_total': len(pages),
            'pages_processed': 0,
            'floorplan_ids': floorplan_ids,
        })

        return page_items, 'ok'

    except JobCancelledError:
        if is_cancel_requested(job_id):
            _mark_file_cancelled(job_id, file_index)
            return None, 'cancelled'
        _mark_file_cancelled(job_id, file_index)
        return None, 'file_cancelled'
    except Exception as e:
        logger.error(f"Failed to ingest PDF {filename}: {e}")
        update_file_status(job_id, file_index, {
            'status': 'error',
            'error': str(e),
            'completed_at': datetime.utcnow().isoformat(),
        })
        return None, 'error'


def detect_floorplan_page(job_id, item, project_id, config, detection_mode, cv_service,
                          ocr_service, active_templates, should_cancel=None):
    """Phase 2: run shape detection + OCR for one ingested page."""
    file_index = item['file_index']
    floorplan_id = item['floorplan_id']
    page_info = item['page_info']
    page_idx = item['page_idx']
    pages_total = item['pages_total']

    if should_cancel is None:
        should_cancel = make_cancel_checker(job_id, file_index)

    def _cancel_result(shapes_detected=0):
        if is_cancel_requested(job_id):
            return 'cancelled', shapes_detected
        return 'file_cancelled', shapes_detected

    page_progress = 25 + (page_idx / max(pages_total, 1)) * 70
    page_t0 = _time.time()

    page_img = cv2.imread(page_info['image_path'])
    if page_img is None:
        logger.error(f"Could not load page image: {page_info['image_path']}")
        return 'error', 0

    update_file_status(job_id, file_index, {
        'status': 'detecting',
        'progress': int(page_progress + 5),
        'pages_processed': page_idx,
    })

    detection_method = config.get('detection_method', 'auto')
    shapes_detected = 0

    try:
        if detection_method == 'auto':
            if cv_service.has_sample_circle(page_info['image_path'], img=page_img):
                detection_method = 'circle'
            else:
                detection_method = 'rectangle'

        detect_t0 = _time.time()
        with cv_service.defer_shape_ocr():
            if detection_method == 'circle':
                marker_colors = config.get('marker_colors') or list(CVService.MARKER_COLORS)
                shapes = cv_service.detect_circles_by_template(
                    page_info['image_path'],
                    params={'marker_colors': marker_colors, 'should_cancel': should_cancel},
                    img=page_img,
                )
                shape_type = 'circle'
            else:
                shapes = cv_service.detect_red_rectangles(
                    page_info['image_path'],
                    params={'should_cancel': should_cancel},
                    img=page_img,
                )
                shape_type = 'rectangle'

            if detection_mode != 'fast' and active_templates:
                try:
                    raw_learned = cv_service.detect_from_learned_templates(
                        page_info['image_path'], active_templates,
                        shape_type=shape_type, img=page_img,
                        should_cancel=should_cancel,
                    )
                    learned_unique = cv_service.deduplicate_with_existing(raw_learned, shapes)
                    if learned_unique:
                        shapes = shapes + learned_unique
                except Exception as tmpl_err:
                    logger.warning(f"Batch: learned template matching failed: {tmpl_err}")

        logger.info(
            f"Page {page_info['page_number']}: primary detection ({shape_type}) "
            f"found {len(shapes)} shapes in {_time.time() - detect_t0:.2f}s"
        )

        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {
                'shape_type': shape_type,
                'status': 'processing',
                'updated_at': datetime.utcnow(),
            }},
        )

        shapes_detected = len(shapes)

        update_file_status(job_id, file_index, {
            'status': 'ocr',
            'progress': int(page_progress + 15),
            'pages_processed': page_idx + 1,
        })

        is_circle = shape_type == 'circle'
        if ocr_service and shapes:
            kept = []
            ocr_t0 = _time.time()
            for idx, shape in enumerate(shapes):
                if idx % 10 == 0 and (is_cancel_requested(job_id) or is_file_cancel_requested(job_id, file_index)):
                    return _cancel_result(shapes_detected)
                try:
                    if shape.get('detection_method') == 'learned' and shape.get('extracted_text'):
                        cleaned = shape['extracted_text']
                        confidence = shape.get('ocr_confidence', 0.0)
                        if not is_valid_sign_code(cleaned, strict=True):
                            continue
                    else:
                        keep, cleaned, confidence = cv_service.run_shape_ocr(page_img, shape)
                        if not keep:
                            continue

                    kept.append((idx, shape, cleaned, confidence))
                except Exception as e:
                    logger.warning(f"OCR failed for shape idx {idx}: {e}")

            logger.info(
                f"Page {page_info['page_number']}: OCR phase kept {len(kept)}/{len(shapes)} "
                f"shapes in {_time.time() - ocr_t0:.2f}s"
            )

            if is_cancel_requested(job_id) or is_file_cancel_requested(job_id, file_index):
                return _cancel_result(shapes_detected)

            quantities = ocr_service.assign_quantities(
                page_img,
                [{
                    'x': shape['x'], 'y': shape['y'],
                    'width': shape['width'], 'height': shape['height'],
                    'center_x': shape.get('center_x'),
                    'center_y': shape.get('center_y'),
                } for _idx, shape, _cleaned, _conf in kept],
            )

            if is_cancel_requested(job_id) or is_file_cancel_requested(job_id, file_index):
                return _cancel_result(shapes_detected)

            for (idx, shape, cleaned, confidence), quantity in zip(kept, quantities):
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
                    shape_data=shape_data,
                )
                doc['extracted_text'] = cleaned
                doc['confidence'] = confidence
                doc['quantity'] = quantity
                if shape.get('detection_method') == 'learned':
                    doc['detection_method'] = 'learned'
                    doc['template_id'] = shape.get('template_id')
                if shape.get('marker_color'):
                    doc['marker_color'] = shape['marker_color']
                mongo.db.extracted_data.insert_one(doc)

        elapsed_seconds = round(_time.time() - page_t0, 1)
        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {
                'status': 'completed',
                'processing_time_seconds': elapsed_seconds,
                'updated_at': datetime.utcnow(),
            }},
        )

        logger.info(
            f"Page {page_info['page_number']}: total page time {elapsed_seconds:.1f}s"
        )
        return 'ok', shapes_detected

    except JobCancelledError:
        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {'status': 'pending', 'updated_at': datetime.utcnow()}},
        )
        return _cancel_result(shapes_detected)
    except Exception as e:
        logger.error(f"Shape detection/OCR failed for floorplan {floorplan_id}: {e}")
        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {'status': 'pending', 'updated_at': datetime.utcnow()}},
        )
        return 'error', shapes_detected


def build_resume_queue(floorplans):
    """Build job file entries and page queue from existing pending floorplans."""
    groups = []
    seen = {}
    for fp in floorplans:
        key = fp.get('pdf_filename') or fp.get('pdf_filepath') or str(fp['_id'])
        if key not in seen:
            seen[key] = len(groups)
            groups.append({'key': key, 'floorplans': []})
        groups[seen[key]]['floorplans'].append(fp)

    job_files = []
    page_queue = []

    for file_index, group in enumerate(groups):
        fps = group['floorplans']
        filename = fps[0].get('pdf_filename') or group['key']
        floorplan_ids = [str(fp['_id']) for fp in fps]

        file_doc = create_processing_file_doc(filename, status='pending')
        file_doc['floorplan_ids'] = floorplan_ids
        file_doc['pages_total'] = len(fps)
        file_doc['pages_processed'] = 0
        file_doc['progress'] = 25
        job_files.append(file_doc)

        for page_idx, fp in enumerate(fps):
            page_queue.append({
                'file_index': file_index,
                'filename': filename,
                'file_path': fp.get('pdf_filepath', ''),
                'floorplan_id': str(fp['_id']),
                'page_info': {
                    'page_number': fp.get('floor_number', page_idx + 1),
                    'image_path': fp['image_filepath'],
                    'preview_path': fp.get('preview_filepath', ''),
                },
                'page_idx': page_idx,
                'pages_total': len(fps),
            })

    return job_files, page_queue


def _run_detection_phase(job_id, page_queue, files_info, project_id, config, detection_mode,
                         ocr_service=None):
    """Run detection + OCR for a prepared page queue."""
    update_job_status(job_id, {'stage': 'detecting'})

    if ocr_service is None:
        try:
            ocr_service = OCRService()
        except Exception as e:
            logger.warning(f"Failed to initialize OCR service: {e}")

    try:
        OCRService._get_shared_ocr()
    except Exception as e:
        logger.warning(f"Failed to warm shared OCR engine: {e}")

    cv_service = CVService(mode=detection_mode)
    active_templates = []
    try:
        active_templates = list(mongo.db.shape_templates.find({'is_active': True}))
    except Exception as e:
        logger.warning(f"Failed to load learned templates: {e}")

    should_cancel = make_cancel_checker(job_id)

    file_stats = {
        fi['index']: {
            'pages_total': 0,
            'pages_done': 0,
            'shapes_detected': 0,
            'floorplan_ids': [],
            'had_error': False,
        }
        for fi in files_info
    }
    for item in page_queue:
        idx = item['file_index']
        file_stats[idx]['pages_total'] = item['pages_total']
        file_stats[idx]['floorplan_ids'].append(item['floorplan_id'])

    for item in page_queue:
        file_index = item['file_index']

        if is_cancel_requested(job_id):
            stats = file_stats[file_index]
            _mark_file_cancelled(
                job_id, file_index,
                pages_processed=stats['pages_done'],
                floorplan_ids=stats['floorplan_ids'],
                shapes_detected=stats['shapes_detected'],
            )
            _finalize_batch_cancel(job_id, file_index + 1)
            logger.info(f"Batch job {job_id} cancelled during detection")
            return 'cancelled', file_stats

        if is_file_cancel_requested(job_id, file_index):
            continue

        file_should_cancel = make_cancel_checker(job_id, file_index)
        result, shapes_count = detect_floorplan_page(
            job_id, item, project_id, config, detection_mode,
            cv_service, ocr_service, active_templates, file_should_cancel,
        )

        stats = file_stats[file_index]
        stats['shapes_detected'] += shapes_count

        if result == 'cancelled':
            stats['pages_done'] = item['page_idx'] + 1
            _mark_file_cancelled(
                job_id, file_index,
                pages_processed=stats['pages_done'],
                floorplan_ids=stats['floorplan_ids'],
                shapes_detected=stats['shapes_detected'],
            )
            _finalize_batch_cancel(job_id, file_index + 1)
            logger.info(f"Batch job {job_id} cancelled during detection of {item['filename']}")
            return 'cancelled', file_stats

        if result == 'file_cancelled':
            stats['pages_done'] = item['page_idx'] + 1
            stats['cancelled'] = True
            _mark_file_cancelled(
                job_id, file_index,
                pages_processed=stats['pages_done'],
                floorplan_ids=stats['floorplan_ids'],
                shapes_detected=stats['shapes_detected'],
            )
            logger.info(f"Batch job {job_id}: file {item['filename']} cancelled by user")
            continue

        if result == 'error':
            stats['had_error'] = True

        stats['pages_done'] = item['page_idx'] + 1
        update_file_status(job_id, file_index, {
            'pages_processed': stats['pages_done'],
            'shapes_detected': stats['shapes_detected'],
            'progress': int(25 + (stats['pages_done'] / max(stats['pages_total'], 1)) * 75),
        })

    job_snapshot = mongo.db.processing_jobs.find_one({'job_id': job_id}, {'files': 1})
    job_files = (job_snapshot or {}).get('files') or []

    for file_info in files_info:
        idx = file_info['index']
        if idx not in file_stats:
            continue
        if idx < len(job_files) and job_files[idx].get('status') == 'cancelled':
            continue
        stats = file_stats[idx]
        if stats.get('cancelled'):
            continue
        update_file_status(job_id, idx, {
            'status': 'completed' if not stats['had_error'] else 'error',
            'progress': 100,
            'pages_processed': stats['pages_done'],
            'shapes_detected': stats['shapes_detected'],
            'floorplan_ids': stats['floorplan_ids'],
            'completed_at': datetime.utcnow().isoformat(),
        })

    return 'ok', file_stats


def process_resume_job(job_id, page_queue, files_info, project_id, config, detection_mode='accurate'):
    """Resume detection for floorplans that were ingested but not yet processed."""
    try:
        update_job_status(job_id, {'status': 'processing', 'stage': 'detecting'})

        if not page_queue:
            update_job_status(job_id, {
                'status': 'completed',
                'processed_files': 0,
                'completed_at': datetime.utcnow(),
                'stage': 'done',
            })
            return

        outcome, file_stats = _run_detection_phase(
            job_id, page_queue, files_info, project_id, config, detection_mode,
        )

        if outcome == 'cancelled':
            return

        error_count = sum(
            1 for stats in file_stats.values()
            if not stats.get('cancelled') and stats['had_error'] and stats['pages_done'] == 0
        )
        processed_count = sum(
            1 for stats in file_stats.values()
            if not stats.get('cancelled') and not (stats['had_error'] and stats['pages_done'] == 0)
        )

        final_status = 'completed' if error_count == 0 else ('error' if processed_count == 0 else 'completed')
        update_job_status(job_id, {
            'status': final_status,
            'processed_files': processed_count + error_count,
            'completed_at': datetime.utcnow(),
            'stage': 'done',
        })

        mongo.db.projects.update_one(
            {'_id': ObjectId(project_id)},
            {'$set': {'status': 'in_progress', 'updated_at': datetime.utcnow()}},
        )

        logger.info(f"Resume job {job_id} completed: {processed_count} succeeded, {error_count} failed")

    except Exception as e:
        logger.error(f"Resume job {job_id} failed: {e}")
        update_job_status(job_id, {
            'status': 'error',
            'completed_at': datetime.utcnow(),
        })


def process_batch_job(job_id, files_info, project_id, upload_folder, config, detection_mode='accurate'):
    """Process all files: ingest every PDF first, then run detection page by page."""
    try:
        update_job_status(job_id, {'status': 'processing', 'stage': 'converting'})

        ocr_service = None
        try:
            ocr_service = OCRService()
        except Exception as e:
            logger.warning(f"Failed to initialize OCR service: {e}")

        page_queue = []
        ingest_errors = 0

        # Phase 1 — convert all PDFs and register floorplans before any CV work
        for file_info in files_info:
            if is_cancel_requested(job_id):
                _finalize_batch_cancel(job_id, file_info['index'])
                logger.info(f"Batch job {job_id} cancelled during ingest")
                return

            if is_file_cancel_requested(job_id, file_info['index']):
                continue

            items, status = ingest_pdf_pages(
                job_id=job_id,
                file_index=file_info['index'],
                file_path=file_info['file_path'],
                filename=file_info['filename'],
                project_id=project_id,
                upload_folder=upload_folder,
                config=config,
                ocr_service=ocr_service,
            )

            if status == 'cancelled':
                _finalize_batch_cancel(job_id, file_info['index'] + 1)
                logger.info(f"Batch job {job_id} cancelled during ingest of {file_info['filename']}")
                return

            if status == 'file_cancelled':
                logger.info(f"Batch job {job_id}: skipped ingest for cancelled file {file_info['filename']}")
                continue

            if status == 'error':
                ingest_errors += 1
                continue

            page_queue.extend(items)

        if not page_queue:
            final_status = 'error' if ingest_errors else 'completed'
            update_job_status(job_id, {
                'status': final_status,
                'processed_files': len(files_info),
                'completed_at': datetime.utcnow(),
                'stage': 'done',
            })
            return

        outcome, file_stats = _run_detection_phase(
            job_id, page_queue, files_info, project_id, config, detection_mode, ocr_service,
        )

        if outcome == 'cancelled':
            return

        processed_count = 0
        error_count = ingest_errors

        for file_info in files_info:
            idx = file_info['index']
            if idx not in file_stats:
                continue
            stats = file_stats[idx]
            if stats.get('cancelled'):
                continue
            if stats['had_error'] and stats['pages_done'] == 0:
                error_count += 1
            else:
                processed_count += 1

        final_status = 'completed' if error_count == 0 else ('error' if processed_count == 0 else 'completed')
        update_job_status(job_id, {
            'status': final_status,
            'processed_files': processed_count + error_count,
            'completed_at': datetime.utcnow(),
            'stage': 'done',
        })

        mongo.db.projects.update_one(
            {'_id': ObjectId(project_id)},
            {'$set': {'status': 'in_progress', 'updated_at': datetime.utcnow()}},
        )

        logger.info(f"Batch job {job_id} completed: {processed_count} succeeded, {error_count} failed")

    except Exception as e:
        logger.error(f"Batch job {job_id} failed: {e}")
        update_job_status(job_id, {
            'status': 'error',
            'completed_at': datetime.utcnow(),
        })


def start_batch_processing(job_id, files_info, project_id, upload_folder, config, detection_mode='accurate'):
    executor.submit(
        process_batch_job,
        job_id,
        files_info,
        project_id,
        upload_folder,
        config,
        detection_mode,
    )


def start_resume_processing(job_id, page_queue, files_info, project_id, config, detection_mode='accurate'):
    executor.submit(
        process_resume_job,
        job_id,
        page_queue,
        files_info,
        project_id,
        config,
        detection_mode,
    )
