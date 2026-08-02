"""Periodic reminder scheduler for uncategorized group images."""
import os
import io
import time
import base64
import logging
import threading
from typing import Optional
from urllib.parse import quote as url_quote

import requests
from PIL import Image
from pymongo import MongoClient

logger = logging.getLogger(__name__)

REMINDER_INTERVAL = int(os.environ.get('GROUP_REMINDER_INTERVAL_MS', 40000)) / 1000
REMINDER_COOLDOWN = 50   # 50s between reminders per sender
FAILED_COOLDOWN = 50     # 50s after send failure
BATCH_GRACE = 5         # seconds


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
        self._client: Optional[MongoClient] = None

    @property
    def db(self):
        if self._client is None:
            self._client = MongoClient(self.mongo_uri)
        return self._client.get_default_database()

    def start(self):
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
                key = f"{img['groupId']}::{img['senderPhone']}"
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

                count = len(images)
                if count == 1:
                    message = f'📷 @{sender_name} 有 1 张图片待归类，请*引用此消息*回复项目编码（如 P-001）。'
                else:
                    message = f'📷 @{sender_name} 有 *{count}* 张图片待归类，请*引用此消息*回复项目编码即可归类全部图片。'

                composite = self._build_composite(images[:9])
                if composite:
                    logger.info('[GroupReminder] Composite built (%d bytes)', len(composite))
                else:
                    logger.warning('[GroupReminder] No composite image available for %s', sender_key)

                resp = self._send_to_group(group_id, message, composite)

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

    def _send_to_group(self, group_id: str, message: str, media_data_uri: Optional[str] = None) -> Optional[dict]:
        try:
            group_url = f'{self.wakka_url}/api/v1/groups/{url_quote(group_id, safe="")}'

            if media_data_uri:
                b64 = media_data_uri.split(',')[1] if ',' in media_data_uri else media_data_uri
                mime_match = media_data_uri.split(';')[0].split(':')[1] if ':' in media_data_uri else 'image/jpeg'
                ext = mime_match.split('/')[1] if '/' in mime_match else 'jpg'
                buf = base64.b64decode(b64)

                files = {'file': (f'image.{ext}', io.BytesIO(buf), mime_match)}
                data = {'caption': message}
                resp = requests.post(
                    f'{group_url}/send-media-upload',
                    headers={'x-api-key': self.wakka_key},
                    files=files, data=data, timeout=30,
                )
            else:
                resp = requests.post(
                    f'{group_url}/send',
                    headers={'Content-Type': 'application/json', 'x-api-key': self.wakka_key},
                    json={'message': message},
                    timeout=15,
                )

            if not resp.ok:
                logger.error('[GroupReminder] Wakka send failed (%d): %s', resp.status_code, resp.text[:200])
                return None
            return resp.json()
        except Exception as e:
            logger.error('[GroupReminder] Network error: %s', e)
            return None

    def _build_composite(self, images: list) -> Optional[str]:
        """Build a composite thumbnail from up to 9 images using Pillow."""
        data_uris = []
        for img in images:
            uri = self._image_to_data_uri(img.get('imagePath'))
            if uri:
                data_uris.append(uri)

        if not data_uris:
            return None
        if len(data_uris) == 1:
            return data_uris[0]

        try:
            THUMB = 400
            thumbs = []
            for uri in data_uris:
                b64 = uri.split(',')[1] if ',' in uri else uri
                pil = Image.open(io.BytesIO(base64.b64decode(b64)))
                pil = pil.convert('RGB')
                pil.thumbnail((THUMB, THUMB))
                canvas = Image.new('RGB', (THUMB, THUMB), (255, 255, 255))
                offset = ((THUMB - pil.width) // 2, (THUMB - pil.height) // 2)
                canvas.paste(pil, offset)
                thumbs.append(canvas)

            cols = min(len(thumbs), 3)
            rows = (len(thumbs) + cols - 1) // cols
            composite = Image.new('RGB', (cols * THUMB, rows * THUMB), (255, 255, 255))
            for i, thumb in enumerate(thumbs):
                composite.paste(thumb, ((i % cols) * THUMB, (i // cols) * THUMB))

            buf = io.BytesIO()
            composite.save(buf, format='JPEG', quality=85)
            return f'data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}'
        except Exception as e:
            logger.error('[GroupReminder] Composite error: %s', e)
            return data_uris[0] if data_uris else None

    def _image_to_data_uri(self, image_path: Optional[str]) -> Optional[str]:
        if not image_path:
            return None
        uploads_root = os.path.dirname(self.media_dir)
        local = image_path.lstrip('/')
        if local.startswith('uploads/'):
            local = local[len('uploads/'):]
        fpath = os.path.join(uploads_root, local)
        if not os.path.isfile(fpath):
            return None
        with open(fpath, 'rb') as f:
            data = f.read()
        ext = os.path.splitext(fpath)[1].lower()
        mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
        mime = mime_map.get(ext, 'image/jpeg')
        return f'data:{mime};base64,{base64.b64encode(data).decode()}'
