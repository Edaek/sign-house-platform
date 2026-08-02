"""Socket.IO client for connecting to Wakka WhatsApp API."""
import logging
import uuid
from typing import Optional, Callable

import socketio

logger = logging.getLogger(__name__)

TYPE_MAP = {
    'chat': 'text',
    'image': 'image',
    'video': 'video',
    'audio': 'audio',
    'ptt': 'audio',
    'document': 'document',
    'location': 'location',
}


class WAMessage:
    __slots__ = (
        'id', 'from_jid', 'from_name', 'author', 'timestamp', 'type',
        'text', 'has_media', 'media_data', 'media_url', 'mime_type',
        'caption', 'has_quoted_msg', 'quoted_msg_id', 'raw',
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class WakkaClient:
    def __init__(self, url: str, api_key: str, app_url: str):
        self.url = url
        self.api_key = api_key
        self.app_url = app_url
        self.sio: Optional[socketio.Client] = None
        self._connected = False
        self._phone: Optional[str] = None
        self._on_message: Optional[Callable] = None
        self._on_ready: Optional[Callable] = None

    def on_message(self, fn: Callable):
        self._on_message = fn

    def on_ready(self, fn: Callable):
        self._on_ready = fn

    def connect(self):
        logger.info('[Wakka] Connecting to %s', self.url)
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=2,
            reconnection_delay_max=30,
        )

        @self.sio.event
        def connect():
            logger.info('[Wakka] Socket.IO connected (sid=%s)', self.sio.sid)

        @self.sio.event
        def disconnect():
            self._connected = False
            logger.warning('[Wakka] Socket.IO disconnected')

        @self.sio.event
        def connect_error(data):
            logger.error('[Wakka] Connection error: %s', data)

        @self.sio.on('whatsapp:ready')
        def on_wa_ready(data):
            self._connected = True
            self._phone = (data or {}).get('phoneNumber')
            logger.info('[Wakka] WhatsApp ready. Phone: %s', self._phone)
            if self._on_ready:
                self._on_ready(self._phone)

        @self.sio.on('whatsapp:qr')
        def on_qr(data):
            logger.info('[Wakka] QR Code received — scan with WhatsApp')
            logger.info('[Wakka] QR: %s', data.get('qr', ''))

        @self.sio.on('whatsapp:authenticated')
        def on_auth():
            logger.info('[Wakka] WhatsApp authenticated')

        @self.sio.on('whatsapp:disconnected')
        def on_wa_disc():
            self._connected = False
            self._phone = None
            logger.warning('[Wakka] WhatsApp session disconnected')

        @self.sio.on('whatsapp:auth_failure')
        def on_auth_fail():
            self._connected = False
            logger.error('[Wakka] WhatsApp auth failure — check API key')

        @self.sio.on('whatsapp:message')
        def on_msg(raw):
            self._handle_incoming(raw)

        @self.sio.on('whatsapp:message_ack')
        def on_ack(data):
            ack_names = {1: 'SENT', 2: 'DELIVERED', 3: 'READ'}
            ack = data.get('ack', 0)
            logger.debug('[Wakka] ACK: %s -> %s', data.get('id'), ack_names.get(ack, ack))

        self.sio.connect(
            self.url,
            auth={'apiKey': self.api_key},
            transports=['websocket', 'polling'],
        )

    def _handle_incoming(self, raw: dict):
        if raw.get('fromMe'):
            return

        raw_id = raw.get('id')
        if isinstance(raw_id, dict) and '_serialized' in raw_id:
            message_id = raw_id['_serialized']
        elif isinstance(raw_id, str):
            message_id = raw_id
        else:
            message_id = str(uuid.uuid4())

        author = raw.get('author') or raw.get('participant')
        msg_type_raw = raw.get('type', 'chat')

        msg = WAMessage(
            id=message_id,
            from_jid=raw.get('from', ''),
            from_name=raw.get('notifyName'),
            author=author,
            timestamp=raw.get('timestamp', 0),
            type=TYPE_MAP.get(msg_type_raw, 'other'),
            text=raw.get('body'),
            has_media=raw.get('hasMedia', False),
            media_data=raw.get('mediaData') or raw.get('data'),
            media_url=raw.get('mediaUrl'),
            mime_type=raw.get('mimetype'),
            caption=raw.get('caption'),
            has_quoted_msg=raw.get('hasQuotedMsg', False),
            quoted_msg_id=self._extract_quoted_id(raw),
            raw=raw,
        )

        if msg.has_media:
            logger.info('[Wakka] Media message (%s) id=%s', msg.type, msg.id)

        if self._on_message:
            self._on_message(msg)

    @staticmethod
    def _extract_quoted_id(raw: dict) -> Optional[str]:
        data = raw.get('_data')
        if isinstance(data, dict) and data.get('quotedStanzaID'):
            return data['quotedStanzaID']
        quoted = raw.get('quotedMsg')
        if isinstance(quoted, dict):
            qid = quoted.get('id')
            if isinstance(qid, dict) and '_serialized' in qid:
                return qid['_serialized']
            if isinstance(qid, str):
                return qid
        return None

    @property
    def is_connected(self):
        return self._connected

    @property
    def phone_number(self):
        return self._phone

    def disconnect(self):
        if self.sio:
            self.sio.disconnect()
        self._connected = False
        self._phone = None
