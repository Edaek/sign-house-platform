"""Periodic reminders for unassigned private-chat Media Pool images."""
import logging
import re
import threading
import time
from datetime import datetime, timezone

from app.services.pool_receipt_notify_service import (
    format_pool_receipt_body,
    mark_pool_images_reminded,
    phone_match_query,
    should_skip_receipt_after_classify_reply,
)
from app.services.wa_send_service import send_message

logger = logging.getLogger(__name__)


class PoolReminderScheduler:
    def __init__(self):
        self._app = None
        self._thread = None
        self._stop = threading.Event()
        self._running = False
        self._failed_until = {}  # phone key -> unix ts

    def init_app(self, app):
        self._app = app

    def start(self):
        if not self._app.config.get('POOL_REMINDER_ENABLED'):
            logger.info('[PoolReminder] Disabled (POOL_REMINDER_ENABLED=false)')
            return
        interval = float(self._app.config.get('POOL_REMINDER_INTERVAL_MS', 40000)) / 1000.0
        if interval <= 0:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(interval,), daemon=True)
        self._thread.start()
        logger.info('[PoolReminder] Polling every %ss for unassigned pool media', interval)

    def stop(self):
        self._stop.set()

    def _loop(self, interval: float):
        while not self._stop.wait(interval):
            if not self._app:
                continue
            with self._app.app_context():
                self._tick()

    def _tick(self):
        if self._running:
            return
        self._running = True
        try:
            from app import mongo

            cooldown = float(self._app.config.get('POOL_REMINDER_COOLDOWN_S', 50))
            grace = float(self._app.config.get('POOL_REMINDER_BATCH_GRACE_S', 5))
            now_utc = datetime.now(timezone.utc)
            now_ts = time.time()

            # Group uploads also mirror into pool_images; those use group_reminder instead.
            # Private uploads always have batchId; group rows use group_reminder instead.
            pending = list(mongo.db.pool_images.find({
                'projectId': {'$exists': False},
                'groupId': {'$exists': False},
            }))
            if not pending:
                return

            by_phone = {}
            for row in pending:
                phone = row.get('phone') or ''
                digits = re.sub(r'\D', '', phone)
                batch = row.get('batchId') or str(row.get('_id'))
                key = f'{digits or phone}:{batch}'
                if not (digits or phone):
                    continue
                by_phone.setdefault(key, []).append(row)

            for key, images in by_phone.items():
                images.sort(key=lambda x: x.get('createdAt') or datetime.min)
                newest = images[-1]
                phone = newest.get('phone') or key
                digits = re.sub(r'\D', '', phone or '')
                if digits and mongo.db.wa_system.find_one({'_id': f'wa_ai_confirm:p:{digits}'}):
                    continue
                if digits and mongo.db.wa_system.find_one({'_id': f'wa_fuzzy_choice:p:{digits}'}):
                    continue

                created = newest.get('createdAt')
                if created:
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if (now_utc - created).total_seconds() < grace:
                        continue

                last_reminded = max(
                    (img.get('lastRemindedAt') for img in images if img.get('lastRemindedAt')),
                    default=None,
                )
                if last_reminded:
                    if last_reminded.tzinfo is None:
                        last_reminded = last_reminded.replace(tzinfo=timezone.utc)
                    if (now_utc - last_reminded).total_seconds() < cooldown:
                        continue

                if now_ts < self._failed_until.get(key, 0):
                    continue

                if should_skip_receipt_after_classify_reply(
                    phone, newest.get('batchId'),
                ):
                    continue

                count = len(images)
                quote_id = newest.get('messageId') or images[0].get('messageId')
                batch_id = newest.get('batchId')
                body = format_pool_receipt_body(count)

                try:
                    from app.services.wa_pool_nudge_service import send_private_classify_nudge

                    resp = send_private_classify_nudge(
                        phone,
                        body,
                        quote_msg_id=quote_id,
                        image_path=newest.get('imagePath'),
                        quoted_payload=newest.get('waMessageRaw'),
                    )
                except Exception:
                    logger.exception('[PoolReminder] Send failed for %s', key)
                    self._failed_until[key] = now_ts + cooldown
                    continue

                if not resp:
                    self._failed_until[key] = now_ts + cooldown
                    continue

                mark_pool_images_reminded(phone, resp, batch_id)
                self._failed_until.pop(key, None)
                logger.info('[PoolReminder] Sent reminder to %s (%d file(s))', key, count)
        except Exception:
            logger.exception('[PoolReminder] Scheduler error')
        finally:
            self._running = False


pool_reminder_scheduler = PoolReminderScheduler()
