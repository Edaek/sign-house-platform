"""Cooperative cancellation for background processing jobs."""

import time
from datetime import datetime

from bson import ObjectId

from app import mongo

_ACTIVE_STATUSES = ('pending', 'processing')


class JobCancelledError(Exception):
    """Raised when a background job should stop processing."""


def make_cancel_checker(job_id: str, file_index: int | None = None, poll_interval: float = 0.2):
    """Return a callable suitable for long-running CV loops.

    Polls Mongo at most every *poll_interval* seconds. Checks whole-job and
    optional per-file cancellation.
    """
    state = {'last_check': 0.0, 'job_cancelled': False, 'file_cancelled': False}

    def should_cancel() -> bool:
        if state['job_cancelled'] or state['file_cancelled']:
            return True
        now = time.time()
        if now - state['last_check'] < poll_interval:
            return False
        state['last_check'] = now
        if is_cancel_requested(job_id):
            state['job_cancelled'] = True
            return True
        if file_index is not None and is_file_cancel_requested(job_id, file_index):
            state['file_cancelled'] = True
            return True
        return False

    return should_cancel


def raise_if_cancelled(should_cancel, step: int = 0, every: int = 1):
    """Invoke *should_cancel* every *every* steps and raise if cancelled."""
    if should_cancel is None:
        return
    if step and step % every != 0:
        return
    if should_cancel():
        raise JobCancelledError()


def request_cancel(job_id: str) -> bool:
    """Mark a job for cancellation. Returns True if a job was updated."""
    result = mongo.db.processing_jobs.update_one(
        {
            'job_id': job_id,
            'status': {'$in': _ACTIVE_STATUSES},
        },
        {'$set': {
            'cancel_requested': True,
            'updated_at': datetime.utcnow(),
        }},
    )
    return result.modified_count > 0


def is_cancel_requested(job_id: str) -> bool:
    job = mongo.db.processing_jobs.find_one({'job_id': job_id}, {'cancel_requested': 1})
    return bool(job and job.get('cancel_requested'))


def is_file_cancel_requested(job_id: str, file_index: int) -> bool:
    job = mongo.db.processing_jobs.find_one({'job_id': job_id}, {'files': 1})
    if not job:
        return False
    files = job.get('files') or []
    if file_index < 0 or file_index >= len(files):
        return False
    return bool(files[file_index].get('cancel_requested'))


def request_cancel_file(job_id: str, file_index: int) -> bool:
    """Request cancellation for a single file within an active batch job."""
    job = mongo.db.processing_jobs.find_one({'job_id': job_id}, {'status': 1, 'files': 1})
    if not job or job.get('status') not in _ACTIVE_STATUSES:
        return False

    files = job.get('files') or []
    if file_index < 0 or file_index >= len(files):
        return False

    f = files[file_index]
    if f.get('status') in ('completed', 'cancelled', 'error'):
        return False

    updates = {
        f'files.{file_index}.cancel_requested': True,
        'updated_at': datetime.utcnow(),
    }
    if f.get('status') in ('pending', 'uploading'):
        updates[f'files.{file_index}.status'] = 'cancelled'
        updates[f'files.{file_index}.error'] = 'Cancelled by user'
        updates[f'files.{file_index}.completed_at'] = datetime.utcnow().isoformat()

    result = mongo.db.processing_jobs.update_one({'job_id': job_id}, {'$set': updates})
    return result.modified_count > 0


def finalize_cancelled(job_id: str, *, error: str | None = None):
    updates = {
        'status': 'cancelled',
        'cancel_requested': True,
        'completed_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
    }
    if error:
        updates['error'] = error
    mongo.db.processing_jobs.update_one({'job_id': job_id}, {'$set': updates})


def cancel_active_jobs_for_project(project_id: str) -> int:
    """Request cancellation for all active jobs belonging to a project."""
    try:
        project_oid = ObjectId(project_id)
        project_filter = {'$or': [{'project_id': project_oid}, {'project_id': project_id}]}
    except Exception:
        project_filter = {'project_id': project_id}

    jobs = mongo.db.processing_jobs.find(
        {
            **project_filter,
            'status': {'$in': _ACTIVE_STATUSES},
        },
        {'job_id': 1},
    )
    count = 0
    for job in jobs:
        if request_cancel(job['job_id']):
            count += 1
    return count


def cancel_remaining_batch_files(job_id: str, from_index: int):
    """Mark unstarted batch files as cancelled."""
    job = mongo.db.processing_jobs.find_one({'job_id': job_id}, {'files': 1})
    if not job:
        return
    files = job.get('files') or []
    for i in range(from_index, len(files)):
        if files[i].get('status') in ('pending', 'uploading'):
            mongo.db.processing_jobs.update_one(
                {'job_id': job_id},
                {'$set': {
                    f'files.{i}.status': 'cancelled',
                    f'files.{i}.error': 'Cancelled by user',
                    f'files.{i}.progress': files[i].get('progress', 0),
                    'updated_at': datetime.utcnow(),
                }},
            )
