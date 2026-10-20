"""Background polling: reflect NAS folder/file changes on the web app."""
import logging
import threading

from app.services.nas_sync_service import run_bidirectional_nas_sync
from app.services.nas_watcher_service import nas_mount

logger = logging.getLogger(__name__)


class NasSyncScheduler:
    def __init__(self):
        self._app = None
        self._thread = None
        self._stop = threading.Event()

    def init_app(self, app):
        self._app = app

    def start(self):
        interval = self._app.config.get('NAS_SYNC_INTERVAL_S', 120)
        if interval <= 0:
            logger.info('[NASSync] Auto-sync disabled (NAS_SYNC_INTERVAL_S=%s)', interval)
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(interval,), daemon=True)
        self._thread.start()
        logger.info('[NASSync] Auto-sync every %ss when NAS mount is available', interval)

    def stop(self):
        self._stop.set()

    def _loop(self, interval):
        while not self._stop.wait(interval):
            if not self._app:
                continue
            with self._app.app_context():
                if not nas_mount.is_available():
                    continue
                try:
                    result = run_bidirectional_nas_sync()
                    if not result.get('ok'):
                        continue
                    pushed = len(result.get('foldersCreated') or [])
                    created = len(result.get('projectsCreated') or [])
                    imported = result.get('recordsImported') or 0
                    removed = result.get('recordsRemoved') or 0
                    if pushed or created or imported or removed:
                        logger.info(
                            '[NASSync] web→NAS %d folder(s), NAS→web +%d project(s), +%d record(s), -%d record(s)',
                            pushed, created, imported, removed,
                        )
                except Exception:
                    logger.exception('[NASSync] Auto-sync failed')


nas_sync_scheduler = NasSyncScheduler()
