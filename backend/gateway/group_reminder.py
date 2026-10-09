"""Periodic reminder scheduler for uncategorized group images."""
import os
import io
import time
import base64
import logging
import threading
from typing import Optional, List
from urllib.parse import quote as url_quote

import requests
from PIL import Image, UnidentifiedImageError
from pymongo import MongoClient

logger = logging.getLogger(__name__)

REMINDER_ENABLED = os.environ.get('GROUP_REMINDER_ENABLED', 'true').lower() == 'true'
REMINDER_INTERVAL = int(os.environ.get('GROUP_REMINDER_INTERVAL_MS', 40000)) / 1000
REMINDER_COOLDOWN = int(os.environ.get('GROUP_REMINDER_COOLDOWN_S', '40'))
FAILED_COOLDOWN = 40
BATCH_GRACE = int(os.environ.get('GROUP_REMINDER_BATCH_GRACE_S', '5'))
ATTACH_COMPOSITE = os.environ.get('GROUP_REMINDER_ATTACH_COMPOSITE', 'false').lower() == 'true'
MAX_SEND_BYTES = 512 * 1024   # cap reminder attachment size for Wakka/WhatsApp
THUMB_SIZE = 400
SINGLE_THUMB_MAX = 800


class GroupReminderScheduler:
    def __init__(self, mongo_uri: str, wakka_url: str, wakka_key: str, media_dir: str):
        self.mongo_uri = mongo_uri
        self.wakka_url = wakka_url
        self.wakka_key = wakka_key
        self.media_dir = media_dir
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._failed_cooldowns = {}   # type: dict
        self._trigger_timers = {}    # type: dict
        self._last_sent_at = {}      # sender_key -> unix ts
        self._client: Optional[MongoClient] = None

    @property
    def db(self):
        if self._client is None:
            self._client = MongoClient(self.mongo_uri)
        return self._client.get_default_database()

    def start(self):
        if not REMINDER_ENABLED:
            logger.info('[GroupReminder] Disabled (GROUP_REMINDER_ENABLED=false)')
            return
        if self._timer:
            return
        logger.info('[GroupReminder] Starting scheduler (interval: %ds)', REMINDER_INTERVAL)
        self._schedule_next()

    def stop(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._client:
            self._client.close()
            self._client = None
        logger.info('[GroupReminder] Scheduler stopped')

    def trigger(self, group_id: str, sender_phone: str):
        """Called when a group image arrives — run reminder after grace period.
        Resets the timer for this sender so rapid-fire images only trigger once."""
        if not REMINDER_ENABLED:
            return
        key = f'{group_id}::{sender_phone}'
        existing = self._trigger_timers.pop(key, None)
        if existing:
            existing.cancel()
        t = threading.Timer(BATCH_GRACE + 1, self._send_reminders)
        t.daemon = True
        t.start()
        self._trigger_timers[key] = t

    def _schedule_next(self):
        self._timer = threading.Timer(REMINDER_INTERVAL, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self):
        self._send_reminders()
        if self._timer is not None:
            self._schedule_next()

    def _send_reminders(self):
        if not REMINDER_ENABLED:
            return
        if self._running:
            return
        self._running = True
        try:
            coll = self.db.group_pending_images
            pending = list(coll.find({'categorized': False}))
            if not pending:
                return

            logger.info('[GroupReminder] Found %d uncategorized image(s)', len(pending))

            by_sender = {}  # type: dict
            for img in pending:
                batch = img.get('batchId') or str(img.get('_id'))
                key = f"{img['groupId']}::{img['senderPhone']}::{batch}"
                by_sender.setdefault(key, []).append(img)

            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc)

            for sender_key, images in by_sender.items():
                images.sort(key=lambda x: x['createdAt'])
                newest = images[-1]
                group_id = images[0]['groupId']
                sender_name = images[0].get('senderName') or images[0]['senderPhone']

                newest_created = newest['createdAt'].replace(tzinfo=timezone.utc)
                if (now_utc - newest_created).total_seconds() < BATCH_GRACE:
                    continue

                last_reminded = max(
                    (img.get('lastRemindedAt') for img in images if img.get('lastRemindedAt')),
                    default=None,
                )
                if last_reminded:
                    lr_utc = last_reminded.replace(tzinfo=timezone.utc)
                    if (now_utc - lr_utc).total_seconds() < REMINDER_COOLDOWN:
                        continue

                now_ts = time.time()
                failed_until = self._failed_cooldowns.get(sender_key, 0)
                if now_ts < failed_until:
                    continue

                last_local = self._last_sent_at.get(sender_key, 0)
                if now_ts - last_local < REMINDER_COOLDOWN:
                    continue

                count = len(images)
                batch_id = newest.get('batchId')
                try:
                    from app.services.pool_receipt_notify_service import (
                        format_pool_receipt_body,
                        should_skip_receipt_after_classify_reply,
                    )
                    if should_skip_receipt_after_classify_reply(
                        batch_id=batch_id,
                        group_id=group_id,
                        group_sender=images[0]['senderPhone'],
                    ):
                        continue
                    message = format_pool_receipt_body(count)
                except Exception:
                    if count == 1:
                        message = (
                            '📷 有 1 張圖片待歸類，請*引用此訊息*回覆專案編碼（如 P-001）或專案名稱。'
                        )
                    else:
                        message = (
                            f'📷 有 *{count}* 張圖片待歸類，請*引用此訊息*回覆專案編碼或專案名稱即可歸類全部圖片。'
                        )

                composite = None
                if ATTACH_COMPOSITE:
                    composite = self._build_composite(images[:9])
                    if composite:
                        logger.info('[GroupReminder] Composite built (%d bytes)', len(composite))
                    else:
                        logger.warning('[GroupReminder] No composite image available for %s', sender_key)

                quote_id = newest.get('messageId') or images[0].get('messageId')
                wa_raw = newest.get('waMessageRaw')
                resp = self._send_to_group(
                    group_id,
                    message,
                    composite,
                    quoted_msg_id=quote_id,
                    quoted_payload=wa_raw,
                )

                now_dt = datetime.now(timezone.utc)
                if resp:
                    msg_id = resp.get('messageId', '')
                    for img in images:
                        update = {
                            'reminderCount': img.get('reminderCount', 0) + 1,
                            'lastRemindedAt': now_dt,
                            'botReminderMsgId': msg_id,
                        }
                        coll.update_one({'_id': img['_id']}, {
                            '$set': update,
                            '$push': {'botReminderMsgIds': msg_id},
                        })
                    self._failed_cooldowns.pop(sender_key, None)
                    self._last_sent_at[sender_key] = now_ts
                    logger.info('[GroupReminder] Sent reminder for %s (%d images)', sender_key, count)
                else:
                    self._failed_cooldowns[sender_key] = now_ts + FAILED_COOLDOWN
                    for img in images:
                        coll.update_one({'_id': img['_id']}, {'$set': {'lastRemindedAt': now_dt}})
                    logger.warning('[GroupReminder] Send failed for %s, cooldown applied', sender_key)

        except Exception:
            logger.exception('[GroupReminder] Scheduler error')
        finally:
            self._running = False

    def _send_to_group(
        self,
        group_id: str,
        message: str,
        media_data_uri: Optional[str] = None,
        *,
        quoted_msg_id: Optional[str] = None,
        quoted_payload=None,
        _retry_without_media: bool = False,
    ) -> Optional[dict]:
        try:
            group_url = f'{self.wakka_url}/api/v1/groups/{url_quote(group_id, safe="")}'
            body = {'message': message}
            if media_data_uri and not _retry_without_media:
                body['mediaUrl'] = media_data_uri
            if quoted_msg_id:
                raw = str(quoted_msg_id).strip()
                parts = raw.split('_')
                stanza = parts[-1] if len(parts) >= 3 else raw
                body['quotedMsg'] = raw
                body['quotedMessageId'] = raw
                body['quotedStanzaId'] = stanza
            if quoted_payload is not None:
                import json
                if isinstance(quoted_payload, str):
                    body['quotedMsgPayload'] = quoted_payload
                else:
                    body['quotedMsgPayload'] = json.dumps(
                        quoted_payload, ensure_ascii=False, default=str,
                    )

            resp = requests.post(
                f'{group_url}/send',
                headers={'Content-Type': 'application/json', 'x-api-key': self.wakka_key},
                json=body,
                timeout=30,
            )

            if not resp.ok:
                logger.error(
                    '[GroupReminder] Wakka send failed (%d): %s',
                    resp.status_code, resp.text[:200],
                )
                if media_data_uri and not _retry_without_media:
                    logger.info('[GroupReminder] Retrying without media attachment')
                    return self._send_to_group(
                        group_id,
                        message,
                        media_data_uri=None,
                        quoted_msg_id=quoted_msg_id,
                        quoted_payload=quoted_payload,
                        _retry_without_media=True,
                    )
                return None
            return resp.json()
        except Exception as e:
            logger.error('[GroupReminder] Network error: %s', e)
            return None

    def _resolve_image_path(self, image_path: Optional[str]) -> Optional[str]:
        if not image_path:
            return None
        uploads_root = os.path.dirname(self.media_dir)
        local = image_path.lstrip('/')
        if local.startswith('uploads/'):
            local = local[len('uploads/'):]
        fpath = os.path.join(uploads_root, local)
        if not os.path.isfile(fpath):
            logger.warning('[GroupReminder] Image file missing: %s', fpath)
            return None
        return fpath

    def _pil_from_path(self, image_path: Optional[str]) -> Optional[Image.Image]:
        fpath = self._resolve_image_path(image_path)
        if not fpath:
            return None
        try:
            with Image.open(fpath) as pil:
                return pil.convert('RGB')
        except (UnidentifiedImageError, OSError, ValueError) as e:
            logger.warning('[GroupReminder] Invalid image %s: %s', fpath, e)
            return None

    @staticmethod
    def _encode_jpeg_data_uri(pil: Image.Image, max_side: int, quality: int = 85) -> str:
        img = pil.copy()
        img.thumbnail((max_side, max_side))
        quality = 85
        while quality >= 50:
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality, optimize=True)
            raw = buf.getvalue()
            if len(raw) <= MAX_SEND_BYTES:
                return f'data:image/jpeg;base64,{base64.b64encode(raw).decode()}'
            quality -= 10
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=50, optimize=True)
        return f'data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}'

    def _build_composite(self, images: list) -> Optional[str]:
        """Build a composite thumbnail from up to 9 images using Pillow."""
        thumbs: List[Image.Image] = []
        for img in images:
            pil = self._pil_from_path(img.get('imagePath'))
            if pil is None:
                continue
            pil.thumbnail((THUMB_SIZE, THUMB_SIZE))
            canvas = Image.new('RGB', (THUMB_SIZE, THUMB_SIZE), (255, 255, 255))
            offset = ((THUMB_SIZE - pil.width) // 2, (THUMB_SIZE - pil.height) // 2)
            canvas.paste(pil, offset)
            thumbs.append(canvas)

        if not thumbs:
            return None
        if len(thumbs) == 1:
            return self._encode_jpeg_data_uri(thumbs[0], SINGLE_THUMB_MAX)

        try:
            cols = min(len(thumbs), 3)
            rows = (len(thumbs) + cols - 1) // cols
            composite = Image.new('RGB', (cols * THUMB_SIZE, rows * THUMB_SIZE), (255, 255, 255))
            for i, thumb in enumerate(thumbs):
                composite.paste(thumb, ((i % cols) * THUMB_SIZE, (i // cols) * THUMB_SIZE))

            return self._encode_jpeg_data_uri(composite, cols * THUMB_SIZE)
        except Exception as e:
            logger.error('[GroupReminder] Composite error: %s', e)
            return self._encode_jpeg_data_uri(thumbs[0], SINGLE_THUMB_MAX)
