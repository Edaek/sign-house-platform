"""Generate unique reference numbers for WA records."""
import time
import logging
from datetime import datetime
from app import mongo

logger = logging.getLogger(__name__)
MAX_RETRIES = 3

def generate_reference_number():
    now = datetime.utcnow()
    prefix = f'SUB-{now.month:02d}{now.day:02d}'
    
    for attempt in range(MAX_RETRIES):
        import re
        count = mongo.db.wa_records.count_documents({
            'referenceNumber': {'$regex': f'^{re.escape(prefix)}'}
        })
        seq = f'{count + 1:03d}'
        candidate = f'{prefix}-{seq}'
        existing = mongo.db.wa_records.find_one({'referenceNumber': candidate})
        if not existing:
            return candidate
        logger.warning(f'[RefNum] Collision on {candidate}, retrying (attempt {attempt + 1})')
    
    # Fallback
    import base64
    fallback = base64.b32encode(int(time.time()).to_bytes(4, 'big')).decode()[:4].upper()
    return f'{prefix}-{fallback}'
