"""Run group uncategorized-image reminders inside the Flask process."""
import logging
import os

from gateway.group_reminder import GroupReminderScheduler

logger = logging.getLogger(__name__)

_runner: GroupReminderScheduler | None = None


def init_app(app) -> None:
    global _runner
    if not app.config.get('GROUP_REMINDER_ENABLED'):
        logger.info('[GroupReminder] Disabled (GROUP_REMINDER_ENABLED=false)')
        return
    media_dir = app.config.get('WA_UPLOADS_FOLDER') or os.path.join(
        app.root_path, 'uploads', 'wa-media',
    )
    _runner = GroupReminderScheduler(
        mongo_uri=app.config['MONGO_URI'],
        wakka_url=app.config.get('WAKKA_API_URL', ''),
        wakka_key=app.config.get('WAKKA_API_KEY', ''),
        media_dir=media_dir,
    )


def start() -> None:
    if _runner:
        _runner.start()
