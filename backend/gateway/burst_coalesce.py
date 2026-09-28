"""Coalesce rapid-fire media messages from one sender into a single inbound POST."""
import logging
import re
import threading
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

    @staticmethod
    def _key(msg: 'WAMessage') -> str:
        is_group = msg.from_jid.endswith('@g.us')
        sender = (msg.author if is_group and msg.author else msg.from_jid) or msg.from_jid
        if is_group:
            return f'g:{msg.from_jid}:{_normalize_sender_jid(sender)}'
        return f'p:{_normalize_sender_jid(sender)}'

    def submit(self, msg: 'WAMessage', photos: List[str], has_media: bool) -> None:
        if not has_media or not photos:
            return

        key = self._key(msg)
        with self._lock:
            buf = self._bufs.get(key)
            if not buf:
                buf = {'items': [], 'timer': None}
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
        self._forward(primary, all_photos, True, message_ids=all_msg_ids)
