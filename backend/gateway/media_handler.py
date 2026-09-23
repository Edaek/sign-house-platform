"""Download and save WhatsApp media files to local storage."""
import os
import time
import hashlib
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

MIME_TO_EXT = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/gif': '.gif',
    'video/mp4': '.mp4',
    'video/3gpp': '.3gp',
    'audio/ogg': '.ogg',
    'audio/ogg; codecs=opus': '.ogg',
    'audio/mpeg': '.mp3',
    'application/pdf': '.pdf',
    'application/msword': '.doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/vnd.ms-excel': '.xls',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
}

TYPE_TO_MIME = {
    'image': 'image/jpeg',
    'video': 'video/mp4',
    'audio': 'audio/ogg',
    'document': 'application/pdf',
}


def get_ext(mime_type: Optional[str], msg_type: str = 'image') -> str:
    if mime_type and mime_type in MIME_TO_EXT:
        return MIME_TO_EXT[mime_type]
    fallback = TYPE_TO_MIME.get(msg_type, 'application/octet-stream')
    return MIME_TO_EXT.get(fallback, '.bin')


def _generate_filename(ext: str) -> str:
    return f'{int(time.time() * 1000)}-{hashlib.md5(os.urandom(8)).hexdigest()[:8]}{ext}'


def _save_buffer(data: bytes, ext: str, media_dir: str) -> str:
    os.makedirs(media_dir, exist_ok=True)
    fname = _generate_filename(ext)
    fpath = os.path.join(media_dir, fname)
    with open(fpath, 'wb') as f:
        f.write(data)
    logger.info('[Media] Saved: %s (%d bytes)', fpath, len(data))
    return f'/uploads/wa-media/{fname}'


def _save_base64(b64_data: str, ext: str, media_dir: str) -> str:
    import base64
    raw = b64_data.split(',')[1] if ',' in b64_data else b64_data
    data = base64.b64decode(raw)
    return _save_buffer(data, ext, media_dir)


def _download_from_url(url: str, ext: str, media_dir: str, api_url: str, api_key: str) -> Optional[str]:
    full_url = url if url.startswith('http') else f'{api_url}{url}'
    headers = {}
    if not url.startswith('http') and api_key:
        headers['x-api-key'] = api_key

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(full_url, headers=headers, timeout=15)
            if resp.ok:
                return _save_buffer(resp.content, ext, media_dir)
            if resp.status_code >= 500 and attempt < max_retries:
                time.sleep(attempt * 2)
                continue
            logger.error('[Media] Download failed: %d %s', resp.status_code, full_url[:150])
            return None
        except Exception as e:
            logger.error('[Media] Download error (attempt %d): %s', attempt, e)
            if attempt < max_retries:
                time.sleep(attempt * 2)
                continue
            return None
    return None


def _download_from_wakka(message_id: str, api_url: str, api_key: str) -> Optional[bytes]:
    if not api_key:
        return None
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(
                f'{api_url}/api/v1/messages/{requests.utils.quote(message_id, safe="")}/media',
                headers={'x-api-key': api_key},
                timeout=15,
            )
            if resp.status_code == 404:
                return None
            if not resp.ok:
                if resp.status_code >= 500 and attempt < max_retries:
                    time.sleep(attempt * 2)
                    continue
                return None
            logger.info('[Media] Downloaded %d bytes from Wakka', len(resp.content))
            return resp.content
        except Exception as e:
            logger.error('[Media] Wakka download error: %s', e)
            if attempt < max_retries:
                time.sleep(attempt * 2)
                continue
            return None
    return None


def handle_media_message(msg, media_dir: str, api_url: str, api_key: str) -> Optional[str]:
    """Download media from a WAMessage and save locally. Returns relative path or None."""
    if not msg.has_media:
        return None

    ext = get_ext(msg.mime_type, msg.type)

    if msg.media_data:
        return _save_base64(msg.media_data, ext, media_dir)

    if msg.media_url:
        return _download_from_url(msg.media_url, ext, media_dir, api_url, api_key)

    buf = _download_from_wakka(msg.id, api_url, api_key)
    if buf:
        return _save_buffer(buf, ext, media_dir)

    logger.warning('[Media] Could not download media for message %s', msg.id)
    return None
