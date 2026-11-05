"""Coalesce rapid-fire media messages from one sender into a single inbound POST."""
import logging
import re
import threading
import time
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from gateway.wakka_client import WAMessage

logger = logging.getLogger(__name__)

BURST_GRACE_S = float(__import__('os').environ.get('GATEWAY_MEDIA_BURST_S', '4.0'))


def _normalize_sender_jid(jid: str) -> str:
    if not jid:
        return ''
    base = re.sub(r'@(c\.us|s\.whatsapp\.net|lid)$', '', jid, flags=re.I)
    digits = re.sub(r'\D', '', base)
    return digits or base


class MediaBurstCoalescer:
    def __init__(self, forward_fn: Callable):
        self._forward = forward_fn
        self._lock = threading.Lock()
        self._bufs: Dict[str, dict] = {}
        self._recent: Dict[str, dict] = {}
        self._recent_ttl_s = float(__import__('os').environ.get('GATEWAY_CAPTION_DEDUP_S', '12'))

    @staticmethod
    def _key(msg: 'WAMessage') -> str:
        is_group = msg.from_jid.endswith('@g.us')
        sender = (msg.author if is_group and msg.author else msg.from_jid) or msg.from_jid
        if is_group:
            return f'g:{msg.from_jid}:{_normalize_sender_jid(sender)}'
        return f'p:{_normalize_sender_jid(sender)}'

    def remember_forwarded_media(self, msg: 'WAMessage', caption: str = '') -> None:
        key = self._key(msg)
        with self._lock:
            self._recent[key] = {
                'at': time.time(),
                'caption': (caption or msg.caption or msg.text or '').strip(),
                'classify_text': '',
            }

    def submit(self, msg: 'WAMessage', photos: List[str], has_media: bool) -> None:
        if not has_media or not photos:
            return

        key = self._key(msg)
        with self._lock:
            buf = self._bufs.get(key)
            if not buf:
                buf = {'items': [], 'timer': None, 'classify_text': ''}
                self._bufs[key] = buf
            buf['items'].append({'msg': msg, 'photos': list(photos)})
            if buf['timer']:
                buf['timer'].cancel()
            t = threading.Timer(BURST_GRACE_S, self._flush, args=(key,))
            t.daemon = True
            t.start()
            buf['timer'] = t
            logger.info(
                '[Gateway] Burst buffer %s: +%d file(s), waiting %.1fs',
                key, len(photos), BURST_GRACE_S,
            )

    def attach_classify_text(self, msg: 'WAMessage') -> bool:
        """If a media burst is open, attach follow-up project code text (e.g. 3026)."""
        text = (msg.text or msg.caption or '').strip()
        if not text or text.lower() in ('projects', 'help', 'skip'):
            return False
        key = self._key(msg)
        with self._lock:
            buf = self._bufs.get(key)
            if buf and buf.get('items'):
                buf['classify_text'] = text
                logger.info('[Gateway] Attached classify text to burst %s: %s', key, text[:40])
                return True
            recent = self._recent.get(key)
            if not recent:
                return False
            if time.time() - float(recent.get('at') or 0) > self._recent_ttl_s:
                return False
            prev = (recent.get('caption') or recent.get('classify_text') or '').strip()
            if prev and prev.casefold() == text.casefold():
                logger.info('[Gateway] Swallow duplicate caption after media %s: %s', key, text[:40])
                return True
            return False

    def _flush(self, key: str) -> None:
        with self._lock:
            buf = self._bufs.pop(key, None)
        if not buf or not buf['items']:
            return

        primary = buf['items'][0]['msg']
        all_photos: List[str] = []
        all_msg_ids: List[str] = []
        for item in buf['items']:
            m = item['msg']
            for i, path in enumerate(item['photos']):
                all_photos.append(path)
                all_msg_ids.append(m.id if i == 0 else f'{m.id}#{i}')

        logger.info(
            '[Gateway] Burst flush %s: %d message(s) → %d file(s), quote %s',
            key, len(buf['items']), len(all_photos), primary.id,
        )
        classify_text = (buf.get('classify_text') or '').strip()
        caption = (primary.caption or primary.text or classify_text or '').strip()
        with self._lock:
            self._recent[key] = {
                'at': time.time(),
                'caption': caption,
                'classify_text': classify_text,
            }
        self._forward(
            primary, all_photos, True,
            message_ids=all_msg_ids,
            classify_text=classify_text or None,
        )
