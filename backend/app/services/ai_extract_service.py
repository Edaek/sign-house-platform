"""AI extraction service — uses Ollama for text and image field extraction."""
import os
import json
import time
import base64
import logging

import requests

from app.services.ai_prompts import build_extraction_prompt, build_image_analysis_prompt

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
TIMEOUT = 30


def _get_config():
    from flask import current_app
    return {
        'base_url': current_app.config.get('OLLAMA_BASE_URL', 'http://localhost:11434'),
        'text_model': current_app.config.get('OLLAMA_TEXT_MODEL', 'gemma3:4b'),
        'vision_model': current_app.config.get('OLLAMA_VISION_MODEL', 'llava:latest'),
    }


def _call_ollama(model, prompt, images=None, base_url='http://localhost:11434'):
    """Call Ollama generate API with retry logic."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            payload = {
                'model': model,
                'prompt': prompt,
                'stream': False,
                'options': {'temperature': 0.1, 'num_predict': 1024},
            }
            if images:
                payload['images'] = images

            resp = requests.post(
                f'{base_url}/api/generate',
                json=payload,
                timeout=TIMEOUT,
            )
            if resp.ok:
                return resp.json().get('response', '')
            last_error = RuntimeError(f'Ollama {resp.status_code}: {resp.text[:200]}')
        except requests.exceptions.Timeout:
            logger.warning('[AI] Ollama timeout (model=%s, attempt %d)', model, attempt + 1)
            break
        except Exception as e:
            last_error = e
            time.sleep(2 ** attempt)

    raise last_error or RuntimeError('Ollama call failed')


def _parse_structured(raw):
    """Extract JSON object from Ollama response text."""
    import re
    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


CONFIDENCE_MAP = {'high': 'green', 'medium': 'yellow', 'low': 'red'}


def _resolve_field(raw_value):
    if not raw_value:
        return '', 'gray'

    if isinstance(raw_value, dict) and 'value' in raw_value:
        val = (raw_value.get('value') or '').strip()
        if not val:
            return '', 'gray'
        conf = CONFIDENCE_MAP.get(raw_value.get('confidence', ''), 'gray')
        return val, conf

    val = str(raw_value).strip()
    if not val:
        return '', 'gray'

    if val.startswith('UNCERTAIN:'):
        return val.replace('UNCERTAIN:', '').strip(), 'yellow'

    hedging = ['might', 'possibly', 'maybe', 'unclear', 'perhaps', 'could be']
    if any(w in val.lower() for w in hedging):
        return val, 'yellow'

    return val, 'green'


def extract_from_text(raw_message, fields, type_keyword):
    """Extract fields from text message using Ollama text model."""
    cfg = _get_config()
    try:
        prompt = build_extraction_prompt(raw_message, fields, type_keyword)
        response = _call_ollama(cfg['text_model'], prompt, base_url=cfg['base_url'])
        parsed = _parse_structured(response)

        result = []
        for field in fields:
            name = field.get('name') or field
            raw_val = parsed.get(name)
            value, confidence = _resolve_field(raw_val)
            result.append({'name': name, 'value': value, 'confidence': confidence})

        return {'fields': result, 'success': True}
    except Exception as e:
        logger.error('[AI] Text extraction failed: %s', e)
        result = [{'name': f.get('name', f), 'value': '', 'confidence': 'gray'} for f in fields]
        return {'fields': result, 'success': False, 'error': str(e)}


def extract_from_image(image_path, fields, type_keyword, media_dir=None):
    """Extract fields from image using Ollama vision model."""
    cfg = _get_config()
    try:
        if media_dir is None:
            from flask import current_app
            media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')

        if image_path.startswith('/uploads/'):
            full_path = os.path.join(media_dir, image_path.replace('/uploads/wa-media/', ''))
        elif os.path.isabs(image_path):
            full_path = image_path
        else:
            full_path = os.path.join(media_dir, image_path)

        if not os.path.isfile(full_path):
            raise FileNotFoundError(f'Image not found: {full_path}')

        with open(full_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()

        prompt = build_image_analysis_prompt(type_keyword, fields)
        response = _call_ollama(cfg['vision_model'], prompt, images=[b64], base_url=cfg['base_url'])
        parsed = _parse_structured(response)

        result = []
        for field in fields:
            name = field.get('name') or field
            raw_val = parsed.get(name)
            value, confidence = _resolve_field(raw_val)
            result.append({'name': name, 'value': value, 'confidence': confidence})

        return {'fields': result, 'success': True}
    except Exception as e:
        logger.error('[AI] Image extraction failed: %s', e)
        result = [{'name': f.get('name', f), 'value': '', 'confidence': 'gray'} for f in fields]
        return {'fields': result, 'success': False, 'error': str(e)}


def merge_extractions(text_fields, image_fields):
    """Merge text and image extraction results, preferring higher confidence."""
    confidence_order = ['green', 'yellow', 'red', 'gray']

    merged = []
    image_map = {f['name']: f for f in image_fields}

    for tf in text_fields:
        img_f = image_map.get(tf['name'])
        if not img_f:
            merged.append(tf)
            continue

        t_rank = confidence_order.index(tf['confidence']) if tf['confidence'] in confidence_order else 3
        i_rank = confidence_order.index(img_f['confidence']) if img_f['confidence'] in confidence_order else 3

        if i_rank < t_rank and img_f['value']:
            merged.append(img_f)
        elif tf['value']:
            merged.append(tf)
        else:
            merged.append(img_f)

    return merged
