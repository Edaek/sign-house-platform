"""Extraction runner — orchestrates AI extraction for a WA record."""
import logging

from bson import ObjectId
from app import mongo
from app.services.ai_extract_service import extract_from_text, extract_from_image, merge_extractions

logger = logging.getLogger(__name__)


def run_extraction(record_id):
    """Run AI extraction on a record: text + images → merge → update status."""
    record = mongo.db.wa_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        logger.error('[Extraction] Record not found: %s', record_id)
        return

    record_type = record.get('type', '')
    template = mongo.db.wa_templates.find_one({
        '$or': [
            {'projectId': record.get('projectId'), 'typeName': record_type},
            {'projectId': None, 'typeName': record_type},
        ],
    }, sort=[('projectId', -1)])

    if not template or not template.get('fields'):
        logger.info('[Extraction] No template for type "%s", skipping', record_type)
        return

    fields = template['fields']

    try:
        text_result = extract_from_text(
            record.get('rawMessage', ''),
            fields,
            record_type,
        )
        final_fields = text_result['fields']

        photos = record.get('photos', [])
        if photos:
            for photo in photos:
                img_result = extract_from_image(photo, fields, record_type)
                if img_result['success']:
                    final_fields = merge_extractions(final_fields, img_result['fields'])

        update = {'extractedFields': final_fields}

        required = [f for f in fields if f.get('required')]
        all_filled = all(
            any(ef['name'] == rf['name'] and ef.get('value', '').strip()
                for ef in final_fields)
            for rf in required
        )

        if all_filled:
            from datetime import datetime
            update['status'] = 'awaiting_review'
            mongo.db.wa_records.update_one(
                {'_id': ObjectId(record_id)},
                {
                    '$set': update,
                    '$push': {'statusHistory': {
                        'from': 'incomplete',
                        'to': 'awaiting_review',
                        'timestamp': datetime.utcnow(),
                    }},
                },
            )
        else:
            mongo.db.wa_records.update_one(
                {'_id': ObjectId(record_id)},
                {'$set': update},
            )

        logger.info('[Extraction] Completed for record %s', record.get('referenceNumber', record_id))
    except Exception:
        logger.exception('[Extraction] Failed for %s', record_id)
