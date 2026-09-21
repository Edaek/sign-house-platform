"""Background detect job runner with cooperative cancellation."""

import os
import time
import traceback
import logging
from datetime import datetime

import cv2
from bson import ObjectId

from app import mongo
from app.models import create_extracted_data_doc, serialize_doc
from app.services.cv_service import CVService
from app.services.ocr_service import OCRService, is_valid_sign_code, clean_ocr_text
from app.services.job_cancel import is_cancel_requested, finalize_cancelled, make_cancel_checker, JobCancelledError
from app.services.batch_processor import executor, update_job_status

logger = logging.getLogger(__name__)


def _set_stage(job_id: str, stage: str, progress: int):
    update_job_status(job_id, {'stage': stage, 'progress': progress})


def run_detect_job(job_id: str, floorplan_id: str, params: dict):
    """Run shape detection + OCR for one floorplan in the background."""
    t0 = time.time()
    stage = 'init'

    def _check_cancel():
        if is_cancel_requested(job_id):
            finalize_cancelled(job_id)
            mongo.db.floorplans.update_one(
                {'_id': ObjectId(floorplan_id)},
                {'$set': {'status': 'pending', 'updated_at': datetime.utcnow()}},
            )
            return True
        return False

    try:
        floorplan = mongo.db.floorplans.find_one({'_id': ObjectId(floorplan_id)})
        if not floorplan:
            update_job_status(job_id, {
                'status': 'error',
                'error': 'Floorplan not found',
                'completed_at': datetime.utcnow(),
            })
            return

        update_job_status(job_id, {'status': 'processing', 'stage': 'init', 'progress': 5})
        if _check_cancel():
            return

        should_cancel = make_cancel_checker(job_id)

        shape_type = params.get('shape_type', 'auto')
        detection_mode = params.get('mode', 'accurate')
        marker_colors = params.get('marker_colors')
        normalized_samples = params.get('color_samples') or []

        cv_service = CVService(mode=detection_mode)
        ocr_service = OCRService()
        image_path = floorplan['image_filepath']
        page_img = cv2.imread(image_path)
        if page_img is None:
            raise FileNotFoundError(f"Could not load image: {image_path}")

        stage = 'auto_detect'
        _set_stage(job_id, stage, 15)
        if _check_cancel():
            return

        if shape_type == 'auto':
            if cv_service.has_sample_circle(image_path, img=page_img):
                shape_type = 'circle'
            else:
                shape_type = 'rectangle'

        stage = 'shape_detection'
        _set_stage(job_id, stage, 30)
        if _check_cancel():
            return

        learned_shapes = []
        with cv_service.defer_shape_ocr():
            if shape_type == 'circle':
                detect_params = {'should_cancel': should_cancel}
                if marker_colors is not None:
                    detect_params['marker_colors'] = marker_colors
                if normalized_samples:
                    detect_params['color_samples'] = normalized_samples
                shapes = cv_service.detect_circles_by_template(
                    image_path,
                    params=detect_params,
                    img=page_img,
                )
                detected_type = 'circle'
            else:
                shapes = cv_service.detect_red_rectangles(
                    image_path,
                    params={'should_cancel': should_cancel},
                    img=page_img,
                )
                detected_type = 'rectangle'

            if detection_mode != 'fast':
                try:
                    active_templates = list(mongo.db.shape_templates.find({'is_active': True}))
                    if active_templates:
                        raw_learned = cv_service.detect_from_learned_templates(
                            image_path, active_templates, shape_type=detected_type,
                            img=page_img, should_cancel=should_cancel,
                        )
                        learned_shapes = cv_service.deduplicate_with_existing(raw_learned, shapes)
                except Exception as tmpl_err:
                    logger.warning(f"Learned template matching failed: {tmpl_err}")

        if _check_cancel():
            return

        stage = 'db_update'
        _set_stage(job_id, stage, 60)
        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {
                'shape_type': detected_type,
                'status': 'processing',
                'updated_at': datetime.utcnow(),
            }},
        )
        mongo.db.extracted_data.delete_many({'floorplan_id': ObjectId(floorplan_id)})

        all_shapes = shapes + learned_shapes

        stage = 'ocr'
        _set_stage(job_id, stage, 70)
        is_circle = detected_type == 'circle'
        ocr_results = []
        img_for_ocr = page_img

        kept = []
        for idx, shape in enumerate(all_shapes):
            if idx % 3 == 0 and _check_cancel():
                return

            if shape.get('detection_method') == 'learned' and shape.get('extracted_text'):
                cleaned = shape['extracted_text']
                confidence = shape.get('ocr_confidence', 0.0)
                if not is_valid_sign_code(cleaned, strict=True):
                    continue
            else:
                keep, cleaned, confidence = cv_service.run_shape_ocr(
                    page_img, shape, should_cancel=should_cancel,
                )
                if not keep:
                    continue
                if shape.get('detection_method') == 'color_bar':
                    if not cleaned or not (cleaned[0].isalpha() and any(c.isdigit() for c in cleaned)):
                        continue
                elif '_sub_signs' in shape:
                    for sub in shape['_sub_signs']:
                        kept.append((idx, sub, sub['extracted_text'],
                                     sub.get('ocr_confidence', confidence)))
                    continue

            kept.append((idx, shape, cleaned, confidence))

        if _check_cancel():
            return

        qty_targets = [
            {
                'x': shape['x'], 'y': shape['y'],
                'width': shape['width'], 'height': shape['height'],
                'center_x': shape.get('center_x'),
                'center_y': shape.get('center_y'),
            }
            for _idx, shape, _cleaned, _conf in kept
            if shape.get('detection_method') != 'color_bar'
        ]
        qty_values = (
            ocr_service.assign_quantities(img_for_ocr, qty_targets)
            if img_for_ocr is not None and qty_targets else []
        )
        qty_iter = iter(qty_values)
        quantities = [
            1 if shape.get('detection_method') == 'color_bar' else next(qty_iter, 1)
            for _idx, shape, _cleaned, _conf in kept
        ]

        if _check_cancel():
            return

        for (idx, shape, cleaned, confidence), quantity in zip(kept, quantities):
            if idx % 3 == 0 and _check_cancel():
                return
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
                shape_data=shape_data,
            )
            doc['extracted_text'] = cleaned or None
            doc['display_text'] = cleaned or None
            doc['confidence'] = confidence
            doc['quantity'] = quantity

            if shape.get('detection_method') == 'learned':
                doc['detection_method'] = 'learned'
                doc['template_id'] = shape.get('template_id')

            if shape.get('marker_color'):
                doc['marker_color'] = shape['marker_color']

            result = mongo.db.extracted_data.insert_one(doc)
            doc['_id'] = result.inserted_id
            ocr_results.append(doc)

        matched_template_ids = set()
        for res in ocr_results:
            tid = res.get('template_id')
            if tid and res.get('detection_method') == 'learned':
                matched_template_ids.add(tid)
        for tid in matched_template_ids:
            try:
                mongo.db.shape_templates.update_one(
                    {'_id': ObjectId(tid)},
                    {'$inc': {'match_count': 1}},
                )
            except Exception:
                pass

        elapsed = round(time.time() - t0, 1)
        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {
                'status': 'completed',
                'processing_time_seconds': elapsed,
                'updated_at': datetime.utcnow(),
            }},
        )

        response_results = [serialize_doc(d) for d in ocr_results]
        for res in response_results:
            res['display_text'] = res.get('manual_text') or res.get('extracted_text')

        learned_count = sum(1 for r in ocr_results if r.get('detection_method') == 'learned')
        message = f"Detected and OCR'd {len(response_results)} {detected_type}s"
        if learned_count:
            message += f' ({learned_count} from learned templates)'

        update_job_status(job_id, {
            'status': 'completed',
            'stage': 'done',
            'progress': 100,
            'completed_at': datetime.utcnow(),
            'result': {
                'message': message,
                'shape_type': detected_type,
                'detection_mode': detection_mode,
                'shapes': response_results,
                'detection_info': {
                    'total_detected': len(response_results),
                    'learned_count': learned_count,
                },
                'elapsed': elapsed,
            },
        })

        logger.info(
            f"[detect-job] {job_id} floorplan={floorplan_id} completed in {elapsed:.1f}s — "
            f"{len(response_results)} results",
        )

    except JobCancelledError:
        finalize_cancelled(job_id)
        mongo.db.floorplans.update_one(
            {'_id': ObjectId(floorplan_id)},
            {'$set': {'status': 'pending', 'updated_at': datetime.utcnow()}},
        )
        logger.info(f"[detect-job] {job_id} cancelled by user")
    except Exception as e:
        elapsed = time.time() - t0
        logger.error(
            f"[detect-job] {job_id} FAILED at stage='{stage}' after {elapsed:.1f}s: {e}\n"
            f"{traceback.format_exc()}",
        )
        update_job_status(job_id, {
            'status': 'error',
            'stage': stage,
            'error': str(e),
            'completed_at': datetime.utcnow(),
        })


def start_detect_job(job_id: str, floorplan_id: str, params: dict):
    executor.submit(run_detect_job, job_id, floorplan_id, params)
