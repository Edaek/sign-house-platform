"""Generate unique reference numbers for WA records."""
import logging
import os
import re
import time
from datetime import datetime
from app.services.wa_time import wa_now

from pymongo import ReturnDocument

from app import mongo

logger = logging.getLogger(__name__)
MAX_RETRIES = 8


def _seed_daily_counter(prefix: str, counter_id: str) -> None:
    """Align counter with existing SUB-MMDD-NNN rows (one-time per day)."""
    if mongo.db.wa_system.find_one({'_id': counter_id, 'seeded': True}, {'_id': 1}):
        return
    pattern = f'^{re.escape(prefix)}-(\\d{{3}})$'
    max_seq = 0
    for doc in mongo.db.wa_records.find(
        {'referenceNumber': {'$regex': f'^{re.escape(prefix)}-'}},
        {'referenceNumber': 1},
    ):
        ref = doc.get('referenceNumber') or ''
        m = re.match(pattern, ref)
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    mongo.db.wa_system.update_one(
        {'_id': counter_id},
        {'$max': {'seq': max_seq}, '$set': {'seeded': True, 'prefix': prefix}},
        upsert=True,
    )


def generate_reference_number():
    """Atomically allocate SUB-MMDD-NNN (unique per day)."""
    now = wa_now()
    prefix = f'SUB-{now.month:02d}{now.day:02d}'
    counter_id = f'ref_seq_{prefix}'
    _seed_daily_counter(prefix, counter_id)

    for attempt in range(MAX_RETRIES):
        doc = mongo.db.wa_system.find_one_and_update(
            {'_id': counter_id},
            {'$inc': {'seq': 1}, '$setOnInsert': {'prefix': prefix, 'createdAt': now}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        seq = int(doc.get('seq') or 1)
        candidate = f'{prefix}-{seq:03d}'
        if not mongo.db.wa_records.find_one({'referenceNumber': candidate}, {'_id': 1}):
            return candidate
        logger.warning('[RefNum] Collision on %s, retrying (attempt %s)', candidate, attempt + 1)

    # Last resort — should be extremely rare
    suffix = f'{int(time.time() * 1000) % 100000:05d}-{os.getpid() % 1000:03d}'
    return f'{prefix}-{suffix}'
