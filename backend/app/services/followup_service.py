"""Follow-up service — sends AI-generated questions for missing required fields."""
import logging
from datetime import datetime

import requests
from bson import ObjectId

from app import mongo
from app.services.wa_send_service import send_message
from app.services.ai_prompts import build_followup_prompt

logger = logging.getLogger(__name__)


def _get_config(project_overrides=None):
    org = mongo.db.wa_organizations.find_one()
    defaults = (org or {}).get('defaults', {})
    po = project_overrides or {}
    return {
        'max_rounds': po.get('maxFollowUpRounds', defaults.get('maxFollowUpRounds', 3)),
        'cooldown_minutes': po.get('followUpCooldownMinutes', defaults.get('followUpCooldownMinutes', 30)),
        'quiet_start': po.get('quietHoursStart', defaults.get('quietHoursStart', 22)),
        'quiet_end': po.get('quietHoursEnd', defaults.get('quietHoursEnd', 7)),
        'max_questions': 3,
    }


def _is_quiet_hours(cfg):
    hour = datetime.now().hour
    if cfg['quiet_start'] > cfg['quiet_end']:
        return hour >= cfg['quiet_start'] or hour < cfg['quiet_end']
    return cfg['quiet_start'] <= hour < cfg['quiet_end']


def _is_cooldown(record, cfg):
    last = record.get('lastFollowUpAt')
    if not last:
        return False
    import time
    elapsed = time.time() - last.timestamp()
    return elapsed < cfg['cooldown_minutes'] * 60


def get_missing_required_fields(record):
    """Return list of missing required field names for a record."""
    record_type = record.get('type', '')
    template = mongo.db.wa_templates.find_one({
        '$or': [
            {'projectId': record.get('projectId'), 'typeName': record_type},
            {'projectId': None, 'typeName': record_type},
        ],
    }, sort=[('projectId', -1)])

    if not template:
        return []

    required = [f for f in template.get('fields', []) if f.get('required')]
    extracted = record.get('extractedFields', [])
    missing = []
    for rf in required:
        ef = next((e for e in extracted if e['name'] == rf['name']), None)
        if not ef or not ef.get('value', '').strip():
            missing.append(rf['name'])
    return missing


def should_follow_up(record):
    cfg = _get_config()
    if record.get('followUpRound', 0) >= cfg['max_rounds']:
        return False
    if _is_quiet_hours(cfg):
        return False
    if _is_cooldown(record, cfg):
        return False
    return len(get_missing_required_fields(record)) > 0


def send_follow_up(record_id):
    """Send a follow-up question for missing fields. Returns True if sent."""
    record = mongo.db.wa_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        return False

    cfg = _get_config()
    now = datetime.utcnow()

    if record.get('followUpRound', 0) >= cfg['max_rounds']:
        mongo.db.wa_records.update_one(
            {'_id': ObjectId(record_id)},
            {
                '$set': {'status': 'awaiting_review'},
                '$push': {'statusHistory': {
                    'from': record.get('status', 'incomplete'),
                    'to': 'awaiting_review',
                    'timestamp': now,
                    'reason': 'Max follow-up rounds reached',
                }},
            },
        )
        return False

    if _is_quiet_hours(cfg) or _is_cooldown(record, cfg):
        return False

    missing = get_missing_required_fields(record)
    if not missing:
        mongo.db.wa_records.update_one(
            {'_id': ObjectId(record_id)},
            {
                '$set': {'status': 'awaiting_review'},
                '$push': {'statusHistory': {
                    'from': 'incomplete', 'to': 'awaiting_review', 'timestamp': now,
                }},
            },
        )
        return False

    fields_to_ask = missing[:cfg['max_questions']]

    try:
        from flask import current_app
        ollama_url = current_app.config.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        text_model = current_app.config.get('OLLAMA_TEXT_MODEL', 'gemma3:4b')

        thread = record.get('followUpThread', [])
        context_parts = [f"Q: {e['question']}\nA: {e.get('answer', '(no reply)')}" for e in thread]
        context = '\n'.join(context_parts) or record.get('rawMessage', '')

        extracted_so_far = [
            {'name': f['name'], 'value': f['value']}
            for f in record.get('extractedFields', [])
            if f.get('value', '').strip()
        ]

        prompt = build_followup_prompt(fields_to_ask, context, extracted_so_far)
        resp = requests.post(
            f'{ollama_url}/api/generate',
            json={'model': text_model, 'prompt': prompt, 'stream': False, 'options': {'temperature': 0.3}},
            timeout=30,
        )
        question = resp.json().get('response', '').strip() if resp.ok else None
    except Exception:
        question = None

    if not question:
        question = 'Please provide the following:\n' + '\n'.join(
            f'{i+1}. {f}' for i, f in enumerate(fields_to_ask)
        )

    try:
        send_message(record.get('senderPhone', ''), question)
    except Exception as e:
        logger.error('[FollowUp] Failed to send: %s', e)
        return False

    new_round = record.get('followUpRound', 0) + 1
    update = {
        'followUpRound': new_round,
        'lastFollowUpAt': now,
    }
    if record.get('status') != 'followup':
        update['status'] = 'followup'

    mongo.db.wa_records.update_one(
        {'_id': ObjectId(record_id)},
        {
            '$set': update,
            '$push': {
                'followUpThread': {
                    'question': question,
                    'timestamp': now,
                    'round': new_round,
                },
                'statusHistory': {
                    'from': record.get('status', 'incomplete'),
                    'to': 'followup',
                    'timestamp': now,
                },
            },
        },
    )

    return True


def handle_follow_up_reply(record_id, reply_text):
    """Update the latest unanswered follow-up entry with the reply."""
    record = mongo.db.wa_records.find_one({'_id': ObjectId(record_id)})
    if not record:
        return

    thread = record.get('followUpThread', [])
    for i in reversed(range(len(thread))):
        if not thread[i].get('answer'):
            mongo.db.wa_records.update_one(
                {'_id': ObjectId(record_id)},
                {'$set': {f'followUpThread.{i}.answer': reply_text}},
            )
            break
