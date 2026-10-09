"""NAS local-mount service — manages project folders on a mounted NAS share."""

import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.bmp'}
PHOTO_SUBDIR = 'Photo'
_HK = ZoneInfo('Asia/Hong_Kong')


def _is_image(filename):
    return os.path.splitext(filename.lower())[1] in IMAGE_EXTENSIONS


class NasMountService:
    """Manages project folders on a locally-mounted NAS share (e.g. /Volumes/...)."""

    def __init__(self):
        self._app = None

    def init_app(self, app):
        self._app = app
        if not self.is_available():
            watch = self._watch_dir()
            logger.warning(
                '[NAS] Local mount not found: %s — run backend/scripts/mount_nas_share.sh '
                '(use --via-tunnel on MacBook away from LAN)',
                watch or '(NAS_WATCH_DIR empty)',
            )

    def _watch_dir(self):
        return self._app.config.get('NAS_WATCH_DIR', '') if self._app else ''

    def is_available(self, *, timeout_s: float = 5.0):
        d = self._watch_dir()
        if not d:
            return False

        def _check():
            return os.path.isdir(d)

        if timeout_s <= 0:
            return _check()
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                return pool.submit(_check).result(timeout=timeout_s)
            except FuturesTimeout:
                logger.warning('[NAS] is_available timed out for %s', d)
                return False

    def status(self):
        watch_dir = self._watch_dir()
        available = self.is_available()
        folder_count = 0
        file_count = 0
        if available:
            try:
                entries = list(Path(watch_dir).iterdir())
                for entry in entries:
                    if entry.is_dir() and not entry.name.startswith('.'):
                        folder_count += 1
            except OSError:
                pass
        out = {
            'enabled': bool(watch_dir),
            'connected': available,
            'watchDir': watch_dir,
            'foldersFound': folder_count,
            'filesFound': file_count,
        }
        if watch_dir and not available:
            out['disconnectReason'] = 'mount_missing'
            out['mountHint'] = (
                'Mount the SMB share so this folder exists (Mac Mini: Finder; '
                'MacBook: ./scripts/mount_nas_share.sh --via-tunnel).'
            )
        return out

    @staticmethod
    def _matches_project_dir_name(dir_name, project_code):
        code_u = (project_code or '').upper().strip()
        if not code_u:
            return False
        du = dir_name.upper()
        return (
            du == code_u
            or du.startswith(f'{code_u} ')
            or du.startswith(f'{code_u}_')
            or du.startswith(f'{code_u}-')
        )

    def create_folder(self, project_code):
        """Create a project folder on the NAS mount. Returns the folder path."""
        watch_dir = self._watch_dir()
        if not watch_dir:
            return {'ok': False, 'error': 'NAS_WATCH_DIR not configured'}
        if not os.path.isdir(watch_dir):
            return {'ok': False, 'error': f'NAS mount not accessible: {watch_dir}'}

        existing = self._resolve_project_folder(project_code)
        if existing is not None:
            return {'ok': True, 'path': str(existing), 'existed': True}

        folder_path = os.path.join(watch_dir, project_code)
        try:
            os.makedirs(folder_path, exist_ok=True)
            logger.info('[NAS] Created folder: %s', folder_path)
            return {'ok': True, 'path': folder_path, 'existed': False}
        except OSError as e:
            logger.error('[NAS] Failed to create folder %s: %s', folder_path, e)
            return {'ok': False, 'error': str(e)}

    def _hk_today_str(self):
        return datetime.now(_HK).date().isoformat()

    def ensure_photo_day_dir(self, project_code, day_str=None):
        """Project folder / Photo / YYYY-MM-DD (matches manual NAS layout)."""
        if not self.is_available():
            return None
        day = day_str or self._hk_today_str()
        proj = self._resolve_project_folder(project_code)
        if proj is None:
            created = self.create_folder(project_code)
            if not created.get('ok'):
                return None
            proj = Path(created['path'])
        day_dir = proj / PHOTO_SUBDIR / day
        day_dir.mkdir(parents=True, exist_ok=True)
        return str(day_dir)

    def copy_file_to_project(self, local_file_path, project_code, *, day_str=None):
        """Copy a local file into Photo/YYYY-MM-DD under the project folder."""
        if not self.is_available():
            return {'ok': False, 'error': 'NAS mount not available'}

        day_dir = self.ensure_photo_day_dir(project_code, day_str)
        if not day_dir:
            return {'ok': False, 'error': 'Could not resolve NAS project folder'}

        filename = os.path.basename(local_file_path)
        dest = os.path.join(day_dir, filename)

        if os.path.exists(dest):
            base, ext = os.path.splitext(filename)
            dest = os.path.join(day_dir, f'{base}_{int(time.time())}{ext}')

        try:
            shutil.copy2(local_file_path, dest)
            logger.info('[NAS] Copied %s → %s', filename, dest)
            return {'ok': True, 'path': dest}
        except OSError as e:
            logger.error('[NAS] Copy failed %s: %s', filename, e)
            return {'ok': False, 'error': str(e)}

    def copy_batch_to_project(self, local_file_paths, project_code):
        """Copy multiple files to a project folder. Returns list of results."""
        results = []
        for path in local_file_paths:
            results.append(self.copy_file_to_project(path, project_code))
        return results

    def list_folders(self):
        """List all project folders on the NAS mount."""
        watch_dir = self._watch_dir()
        if not watch_dir or not os.path.isdir(watch_dir):
            return []

        folders = []
        try:
            entries = sorted(Path(watch_dir).iterdir())
        except OSError as e:
            logger.warning('[NAS] list_folders iterdir failed: %s', e)
            return []
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith('.'):
                continue
            # Listing + stat on every file over SMB is slow; counts come from folder_stats per project.
            folders.append({
                'code': entry.name.upper(),
                'folderName': entry.name,
                'fileCount': 0,
                'latestModified': None,
            })
        return folders

    def _resolve_project_folder(self, project_code):
        watch_dir = self._watch_dir()
        if not watch_dir:
            return None
        root = Path(watch_dir)
        if not root.is_dir():
            return None

        direct = root / project_code
        if direct.is_dir():
            return direct

        def find_under(parent: Path, depth: int):
            if depth > 4:
                return None
            try:
                children = [c for c in parent.iterdir() if c.is_dir() and not c.name.startswith('.')]
            except OSError:
                return None
            for d in children:
                if self._matches_project_dir_name(d.name, project_code):
                    return d
            for d in children:
                hit = find_under(d, depth + 1)
                if hit is not None:
                    return hit
            return None

        return find_under(root, 0)

    def folder_stats(self, project_code):
        """Stats for one project folder only (fast — no full NAS scan)."""
        folder = self._resolve_project_folder(project_code)
        if not folder:
            return None
        file_count = 0
        latest_mtime = 0
        photo_root = folder / PHOTO_SUBDIR
        if photo_root.is_dir():
            for f in photo_root.rglob('*'):
                if f.is_file() and _is_image(f.name):
                    file_count += 1
                    mt = f.stat().st_mtime
                    if mt > latest_mtime:
                        latest_mtime = mt
        for f in folder.iterdir():
            if f.is_file() and _is_image(f.name):
                file_count += 1
                mt = f.stat().st_mtime
                if mt > latest_mtime:
                    latest_mtime = mt
        return {
            'code': folder.name.upper(),
            'folderName': folder.name,
            'fileCount': file_count,
            'latestModified': datetime.utcfromtimestamp(latest_mtime).isoformat() if latest_mtime else None,
        }

    def delete_path(self, path):
        """Delete a file or folder under NAS_WATCH_DIR (no-op if already missing)."""
        watch_dir = self._watch_dir()
        if not watch_dir or not path:
            return {'ok': False, 'error': 'NAS not configured'}
        try:
            watch = Path(watch_dir).resolve()
            target = Path(path).resolve()
            if not str(target).startswith(str(watch)):
                return {'ok': False, 'error': 'Path outside NAS watch directory'}
            if not target.exists():
                return {'ok': True, 'missing': True}
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            logger.info('[NAS] Deleted %s', target)
            return {'ok': True}
        except OSError as e:
            logger.warning('[NAS] Delete failed %s: %s', path, e)
            return {'ok': False, 'error': str(e)}

    def delete_project_folder(self, project_code):
        folder = self._resolve_project_folder(project_code)
        if not folder:
            return {'ok': True, 'missing': True}
        return self.delete_path(str(folder))

    def list_folder_files(self, project_code):
        """List image files under Photo/ (and legacy project root)."""
        folder = self._resolve_project_folder(project_code)
        if not folder:
            return []

        files = []
        seen = set()
        photo_root = folder / PHOTO_SUBDIR
        paths = []
        if photo_root.is_dir():
            paths.extend(sorted(photo_root.rglob('*')))
        paths.extend(sorted(folder.iterdir()))
        for f in paths:
            if not f.is_file() or not _is_image(f.name):
                continue
            key = str(f.resolve())
            if key in seen:
                continue
            seen.add(key)
            st = f.stat()
            files.append({
                'name': f.name,
                'size': st.st_size,
                'modified': datetime.utcfromtimestamp(st.st_mtime).isoformat(),
                'relativePath': str(f.relative_to(folder)),
            })
        return files


nas_mount = NasMountService()
