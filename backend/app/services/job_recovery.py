"""Recover stale processing jobs whose in-process workers no longer exist."""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

from bson import ObjectId

from app import mongo

logger = logging.getLogger(__name__)

STALE_ERROR = 'Stale job recovered (no active worker)'


def floorplan_ids_for_job(job) -> List[ObjectId]:
    """Collect floorplan ObjectIds referenced by a processing job."""
    ids = []
    fp_id = job.get('floorplan_id')
    if fp_id:
        ids.append(fp_id if isinstance(fp_id, ObjectId) else ObjectId(fp_id))
    for f in job.get('files') or []:
        for fid in f.get('floorplan_ids') or []:
            try:
                ids.append(fid if isinstance(fid, ObjectId) else ObjectId(fid))
            except Exception:
                continue
    seen = set()
    unique = []
    for oid in ids:
        key = str(oid)
        if key not in seen:
            seen.add(key)
            unique.append(oid)
    return unique


def skip_stale_processing_floorplans(job) -> int:
    """Mark stuck in-progress floorplans as skipped so batch can continue with the next PDF."""
    fp_ids = floorplan_ids_for_job(job)
    if not fp_ids:
        return 0
    result = mongo.db.floorplans.update_many(
        {'_id': {'$in': fp_ids}, 'status': 'processing'},
        {'$set': {
            'status': 'error',
            'processing_error': 'Skipped: processing timed out',
            'updated_at': datetime.utcnow(),
        }},
    )
    return result.modified_count


def _try_auto_resume_project(stale_job) -> bool:
    """Start a resume job for remaining pending floorplans after a stale batch was cleared."""
    import os
    from app.models import create_processing_job_doc
    from app.services.batch_processor import build_resume_queue, start_resume_processing

    project_id = stale_job.get('project_id')
    if not project_id:
        return False

    active = mongo.db.processing_jobs.find_one({
        'project_id': project_id,
        'status': {'$in': ['pending', 'processing']},
    })
    if active:
        return False

    pending = list(mongo.db.floorplans.find({
        'project_id': project_id,
        'status': 'pending',
    }).sort('floor_number', 1))
    pending = [
        fp for fp in pending
        if fp.get('image_filepath') and os.path.exists(fp['image_filepath'])
    ]
    if not pending:
        return False

    user_id = stale_job.get('user_id')
    if not user_id:
        return False

    job_files, page_queue = build_resume_queue(pending)
    job_doc = create_processing_job_doc(
        str(project_id), str(user_id), job_files, job_type='batch_resume',
    )
    job_doc['detection_mode'] = stale_job.get('detection_mode', 'accurate')
    job_doc['paddle_device'] = stale_job.get('paddle_device')
    result = mongo.db.processing_jobs.insert_one(job_doc)
    job_doc['_id'] = result.inserted_id

    config = {
        'detection_method': stale_job.get('detection_method', 'auto'),
        'marker_colors': stale_job.get('marker_colors'),
        'paddle_device': stale_job.get('paddle_device'),
    }
    files_info = [{'index': i, 'filename': f['filename']} for i, f in enumerate(job_files)]
    start_resume_processing(
        job_doc['job_id'], page_queue, files_info, str(project_id),
        config, job_doc['detection_mode'],
    )
    logger.info(
        'Auto-resumed project %s after stale job %s (%d pending floorplan(s))',
        project_id, stale_job.get('job_id'), len(pending),
    )
    return True


def recover_stale_jobs(stale_minutes: Optional[int] = None, project_id=None) -> int:
    """Mark jobs with no worker heartbeat as error/cancelled and unblock floorplans."""
    from flask import current_app

    if stale_minutes is None:
        try:
            stale_minutes = current_app.config.get('JOB_STALE_MINUTES', 30)
        except RuntimeError:
            stale_minutes = 30

    cutoff = datetime.utcnow() - timedelta(minutes=stale_minutes)
    query = {
        'status': {'$in': ['pending', 'processing']},
        'updated_at': {'$lt': cutoff},
    }
    if project_id is not None:
        try:
            query['project_id'] = ObjectId(project_id) if isinstance(project_id, str) else project_id
        except Exception:
            query['project_id'] = project_id

    recovered = 0
    for job in mongo.db.processing_jobs.find(query):
        job_id = job['job_id']
        if job.get('cancel_requested'):
            final_status = 'cancelled'
            error_msg = 'Cancelled — worker stopped (stale job recovered)'
        else:
            final_status = 'error'
            error_msg = STALE_ERROR

        mongo.db.processing_jobs.update_one(
            {'job_id': job_id},
            {'$set': {
                'status': final_status,
                'error': error_msg,
                'completed_at': datetime.utcnow(),
                'updated_at': datetime.utcnow(),
                'recovered_stale': True,
            }},
        )

        for i, f in enumerate(job.get('files') or []):
            if f.get('status') in ('completed', 'cancelled', 'error'):
                continue
            file_status = 'cancelled' if final_status == 'cancelled' else 'error'
            mongo.db.processing_jobs.update_one(
                {'job_id': job_id},
                {'$set': {
                    f'files.{i}.status': file_status,
                    f'files.{i}.error': error_msg,
                    f'files.{i}.completed_at': datetime.utcnow().isoformat(),
                }},
            )

        fp_skipped = skip_stale_processing_floorplans(job)
        logger.warning(
            'Recovered stale job %s → %s (floorplans skipped: %d)',
            job_id, final_status, fp_skipped,
        )
        if job.get('job_type') in (None, 'batch_upload', 'batch_resume'):
            try:
                _try_auto_resume_project(job)
            except Exception:
                logger.exception('Auto-resume after stale job %s failed', job_id)
        recovered += 1

    return recovered


def recover_stale_jobs_for_project(project_id) -> int:
    return recover_stale_jobs(project_id=project_id)


def start_stale_job_watchdog(app):
    """Background thread that periodically recovers stale jobs."""
    interval_sec = app.config.get('JOB_RECOVERY_INTERVAL_MINUTES', 5) * 60
    stale_minutes = app.config.get('JOB_STALE_MINUTES', 30)

    def _loop():
        while True:
            time.sleep(interval_sec)
            try:
                with app.app_context():
                    count = recover_stale_jobs(stale_minutes=stale_minutes)
                    if count:
                        logger.info('Stale job watchdog recovered %d job(s)', count)
            except Exception:
                logger.exception('Stale job watchdog error')

    thread = threading.Thread(target=_loop, daemon=True, name='stale-job-watchdog')
    thread.start()
    logger.info(
        'Stale job watchdog started (interval=%ds, stale_threshold=%dm)',
        interval_sec, stale_minutes,
    )
