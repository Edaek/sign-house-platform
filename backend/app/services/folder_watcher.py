"""Folder watcher service for automatic PDF import.

Watches a local folder for new PDF files, then feeds them into the existing
batch processing pipeline (PDF → images → shape detection → OCR).

Inspired by ocr-audit-main/local-service watcher pattern.
"""

import logging
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app import mongo
from app.services.batch_processor import start_batch_processing
from app.services.cv_service import CVService

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {'.pdf'}
_DEBOUNCE_SECONDS = 3.0
_POLL_INTERVAL = 5


class _WatcherState:
    __slots__ = (
        'thread', 'stop_event', 'project_id', 'watch_folder',
        'detection_mode', 'marker_colors', 'files_processed', 'files_failed',
        'last_error', 'started_at',
    )

    def __init__(self, thread: threading.Thread, stop_event: threading.Event,
                 project_id: str, watch_folder: str, detection_mode: str,
                 marker_colors: Optional[List[str]] = None):
        self.thread = thread
        self.stop_event = stop_event
        self.project_id = project_id
        self.watch_folder = watch_folder
        self.detection_mode = detection_mode
        self.marker_colors = marker_colors or list(CVService.MARKER_COLORS)
        self.files_processed: int = 0
        self.files_failed: int = 0
        self.last_error: str = ''
        self.started_at: str = datetime.utcnow().isoformat()


class FolderWatcherManager:
    """Manages folder-watching threads, one per project."""

    def __init__(self):
        self._watchers: Dict[str, _WatcherState] = {}
        self._lock = threading.Lock()
        self._app = None
        self._upload_folder = ''
        self._config = {}

    def init_app(self, app):
        self._app = app
        self._upload_folder = app.config['UPLOAD_FOLDER']
        self._config = {
            'PDF_DPI': app.config.get('PDF_DPI', 200),
            'PDF_PREVIEW_DPI': app.config.get('PDF_PREVIEW_DPI', 150),
            'TITLE_REGION_X_START': app.config.get('TITLE_REGION_X_START', 60),
            'TITLE_REGION_Y_START': app.config.get('TITLE_REGION_Y_START', 85),
            'TITLE_REGION_WIDTH': app.config.get('TITLE_REGION_WIDTH', 40),
            'TITLE_REGION_HEIGHT': app.config.get('TITLE_REGION_HEIGHT', 15),
        }

    def _watch_loop(self, project_id: str, watch_folder: str,
                    detection_mode: str, marker_colors: List[str],
                    stop_event: threading.Event):
        """Main polling loop that scans folder for new PDFs."""
        watch_path = Path(watch_folder)
        processed_dir = watch_path / 'processed'
        processed_dir.mkdir(parents=True, exist_ok=True)

        pending: Dict[str, float] = {}

        logger.info('[watcher:%s] Watching folder: %s', project_id, watch_path)

        while not stop_event.is_set():
            stop_event.wait(_POLL_INTERVAL)
            if stop_event.is_set():
                break

            try:
                for p in watch_path.iterdir():
                    if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                        key = str(p)
                        if key not in pending:
                            pending[key] = time.time()
            except OSError as e:
                logger.warning('[watcher:%s] Scan error: %s', project_id, e)
                continue

            now = time.time()
            ready = [p for p, t in pending.items()
                     if now - t >= _DEBOUNCE_SECONDS and Path(p).exists()]

            for file_path in ready:
                del pending[file_path]
                logger.info('[watcher:%s] New PDF detected: %s', project_id, file_path)
                self._process_file(project_id, file_path, watch_folder,
                                   detection_mode, marker_colors, processed_dir)

        logger.info('[watcher:%s] Watcher stopped', project_id)

    def _process_file(self, project_id: str, file_path: str,
                      watch_folder: str, detection_mode: str,
                      marker_colors: List[str], processed_dir: Path):
        """Copy PDF into the standard upload tree and kick off batch processing."""
        source = Path(file_path)
        try:
            pdf_dir = Path(self._upload_folder) / 'pdfs' / project_id
            pdf_dir.mkdir(parents=True, exist_ok=True)
            dest_pdf = pdf_dir / source.name
            counter = 1
            while dest_pdf.exists():
                dest_pdf = pdf_dir / f'{source.stem}_{counter}{source.suffix}'
                counter += 1
            shutil.copy2(str(source), str(dest_pdf))

            job_id = str(uuid.uuid4())
            files_info = [{
                'file_path': str(dest_pdf),
                'filename': source.name,
                'index': 0,
            }]

            with self._app.app_context():
                mongo.db.processing_jobs.insert_one({
                    'job_id': job_id,
                    'project_id': project_id,
                    'source': 'folder_watcher',
                    'status': 'pending',
                    'total_files': 1,
                    'processed_files': 0,
                    'files': [{
                        'filename': source.name,
                        'status': 'pending',
                        'progress': 0,
                    }],
                    'created_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow(),
                })

                config = dict(self._config)
                config['marker_colors'] = marker_colors
                start_batch_processing(
                    job_id, files_info, project_id,
                    self._upload_folder, config, detection_mode,
                )

            arch_dest = processed_dir / source.name
            if arch_dest.exists():
                arch_dest = processed_dir / f'{source.stem}_{int(time.time())}{source.suffix}'
            shutil.move(str(source), str(arch_dest))
            logger.info('[watcher:%s] Archived %s → %s', project_id, source.name, arch_dest)

            with self._lock:
                state = self._watchers.get(project_id)
                if state:
                    state.files_processed += 1

        except Exception as exc:
            logger.exception('[watcher:%s] Error processing %s', project_id, file_path)
            with self._lock:
                state = self._watchers.get(project_id)
                if state:
                    state.files_failed += 1
                    state.last_error = str(exc)

    # ── Public API ─────────────────────────────────────────────────────

    def start(self, project_id: str, watch_folder: str,
              detection_mode: str = 'accurate',
              marker_colors: Optional[List[str]] = None):
        marker_colors = marker_colors or list(CVService.MARKER_COLORS)
        with self._lock:
            existing = self._watchers.get(project_id)
            if existing and existing.thread.is_alive():
                logger.warning('[watcher:%s] Already running', project_id)
                return False

        watch_path = Path(watch_folder)
        if not watch_path.is_dir():
            watch_path.mkdir(parents=True, exist_ok=True)

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._watch_loop,
            args=(project_id, watch_folder, detection_mode, marker_colors, stop_event),
            daemon=True,
            name=f'watcher-{project_id}',
        )
        thread.start()

        with self._lock:
            self._watchers[project_id] = _WatcherState(
                thread, stop_event, project_id, watch_folder, detection_mode, marker_colors,
            )
        logger.info('[watcher:%s] Started watching %s (mode=%s, colors=%s)',
                     project_id, watch_folder, detection_mode, marker_colors)
        return True

    def stop(self, project_id: str):
        with self._lock:
            state = self._watchers.pop(project_id, None)
        if state:
            state.stop_event.set()
            state.thread.join(timeout=10)
            logger.info('[watcher:%s] Stopped', project_id)
            return True
        return False

    def stop_all(self):
        with self._lock:
            ids = list(self._watchers.keys())
        for pid in ids:
            self.stop(pid)

    def status(self, project_id: str) -> dict:
        with self._lock:
            state = self._watchers.get(project_id)
        if not state:
            return {
                'status': 'stopped',
                'watch_folder': '',
                'detection_mode': '',
                'files_processed': 0,
                'files_failed': 0,
                'last_error': '',
                'started_at': None,
            }
        return {
            'status': 'running' if state.thread.is_alive() else 'error',
            'watch_folder': state.watch_folder,
            'detection_mode': state.detection_mode,
            'files_processed': state.files_processed,
            'files_failed': state.files_failed,
            'last_error': state.last_error,
            'started_at': state.started_at,
        }

    def all_statuses(self) -> dict:
        with self._lock:
            ids = list(self._watchers.keys())
        return {pid: self.status(pid) for pid in ids}


watcher_manager = FolderWatcherManager()
