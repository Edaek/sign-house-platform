"""Loomy-mode reminder: every ~60s while pool rows stay unassigned and not dismissed."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 60
DEFAULT_COOLDOWN_S = 60
DEFAULT_GRACE_S = 60
# 0 = unlimited rounds until assigned or dismissed
DEFAULT_MAX_ROUNDS = 0


class LoomyPoolReminder:
    def __init__(self):
        self._app = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._running = False
        self._failed_until: dict[str, float] = {}

    def init_app(self, app):
        self._app = app

    def start(self):
        from app.services.wa_classify_mode import wa_inbound_loomy_dispatch_enabled

        if not wa_inbound_loomy_dispatch_enabled():
            logger.info('[LoomyReminder] Disabled (not in agent/loomy mode)')
            return

        enabled = os.environ.get('LOOMY_POOL_REMINDER_ENABLED', 'false').strip().lower()
        if enabled not in ('1', 'true', 'yes', 'on'):
            logger.info(
                '[LoomyReminder] Off — pool nudge/remind via Loom (LOOMY_POOL_REMINDER_ENABLED=true to override)',
            )
            return

        if self._thread and self._thread.is_alive():
            return

        interval = float(os.environ.get('LOOMY_POOL_REMINDER_INTERVAL_S', str(DEFAULT_INTERVAL_S)))
        if interval <= 0:
            return

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, args=(interval,), daemon=True, name='loomy-pool-reminder',
        )
        self._thread.start()
        logger.info('[LoomyReminder] Polling every %ss for unassigned pool media', interval)

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
            self._do_tick()
        except Exception:
            logger.exception('[LoomyReminder] Scheduler error')
        finally:
            self._running = False

    def _do_tick(self):
        from app import mongo

        interval = float(os.environ.get('LOOMY_POOL_REMINDER_INTERVAL_S', str(DEFAULT_INTERVAL_S)))
        cooldown = float(os.environ.get('LOOMY_POOL_REMINDER_COOLDOWN_S', str(DEFAULT_COOLDOWN_S)))
        if cooldown <= 0:
            cooldown = interval
        grace = float(os.environ.get('LOOMY_POOL_REMINDER_GRACE_S', str(DEFAULT_GRACE_S)))
        max_rounds = int(os.environ.get('LOOMY_POOL_REMINDER_MAX_ROUNDS', str(DEFAULT_MAX_ROUNDS)))
        now_utc = datetime.now(timezone.utc)
        now_ts = time.time()

        pending = list(mongo.db.pool_images.find({
            'projectId': {'$exists': False},
            'dismissed': {'$ne': True},
        }))
        if not pending:
            return

        from app.services.loomy_pool_batch import batch_key_for_doc, sender_bucket_key

        by_batch: dict[str, list] = {}
        for row in pending:
            phone = row.get('phone') or ''
            digits = re.sub(r'\D', '', phone)
            chat_jid = (row.get('chatJid') or '').strip()
            if not (digits or phone):
                continue
            bucket = sender_bucket_key(phone=phone, chat_jid=chat_jid)
            batch = batch_key_for_doc(row)
            key = f'{bucket}|{batch}'
            by_batch.setdefault(key, []).append(row)

        for key, images in by_batch.items():
            images.sort(key=lambda x: x.get('createdAt') or datetime.min)
            newest = images[-1]
            phone = newest.get('phone') or ''
            digits = re.sub(r'\D', '', phone)
            chat_jid = (newest.get('chatJid') or '').strip()
            group_jid = chat_jid if '@g.us' in chat_jid else None

            from app.services.loomy_wa_classify_guard import loomy_classify_running

            if loomy_classify_running(phone=digits or phone, group_id=group_jid):
                continue

            created = newest.get('createdAt')
            if created:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if (now_utc - created).total_seconds() < grace:
                    continue

            remind_count = max(
                (img.get('loomyReminderCount', 0) for img in images),
                default=0,
            )
            if max_rounds > 0 and remind_count >= max_rounds:
                continue

            last_reminded = max(
                (img.get('loomyLastRemindedAt') for img in images if img.get('loomyLastRemindedAt')),
                default=None,
            )
            if last_reminded:
                if last_reminded.tzinfo is None:
                    last_reminded = last_reminded.replace(tzinfo=timezone.utc)
                if (now_utc - last_reminded).total_seconds() < cooldown:
                    continue

            if now_ts < self._failed_until.get(key, 0):
                continue

            count = len(images)
            quote_id = newest.get('messageId') or images[0].get('messageId')
            is_group = key.startswith('g:')
            cap = ''
            for img in images:
                c = (img.get('caption') or '').strip()
                if c:
                    cap = c[:60]
                    break
            cap_line = f'「{cap}」\n' if cap else ''

            message = (
                f'📷 待歸類{cap_line}'
                f'（此則 {count} 張）\n'
                f'請**回覆本則消息**（或引用原圖）並寫專案編號；要略過請回覆「不用」。\n'
                f'發 *projects* 查看專案列表。'
            )

            try:
                from app.services.loomy_pool_batch import mark_loomy_reminder_bot_ids
                from app.services.wa_send_service import send_group_message, send_message

                send_resp = None
                if is_group:
                    bucket = key.split('|', 1)[0]
                    parts = bucket.split(':', 2)
                    group_jid = parts[1] if len(parts) >= 2 else ''
                    if group_jid:
                        send_resp = send_group_message(group_jid, message, quoted_msg_id=quote_id)
                    else:
                        continue
                else:
                    send_resp = send_message(digits or phone, message, quoted_msg_id=quote_id)
            except Exception:
                logger.exception('[LoomyReminder] Send failed for %s', key)
                self._failed_until[key] = now_ts + cooldown
                continue

            ids = [str(img['_id']) for img in images]
            mark_loomy_reminder_bot_ids(ids, send_resp if isinstance(send_resp, dict) else None)
            self._failed_until.pop(key, None)
            logger.info('[LoomyReminder] Sent reminder to %s (%d file(s), round %d)', key, count, remind_count + 1)


loomy_pool_reminder = LoomyPoolReminder()
