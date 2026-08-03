"""NAS local-mount service — manages project folders on a mounted NAS share."""

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.bmp'}


def _is_image(filename):
    return os.path.splitext(filename.lower())[1] in IMAGE_EXTENSIONS


class NasMountService:
    """Manages project folders on a locally-mounted NAS share (e.g. /Volumes/...)."""

    def __init__(self):
        self._app = None

    def init_app(self, app):
        self._app = app

    def _watch_dir(self):
        return self._app.config.get('NAS_WATCH_DIR', '') if self._app else ''

    def is_available(self):
        d = self._watch_dir()
        return bool(d) and os.path.isdir(d)

    def status(self):
        watch_dir = self._watch_dir()
        available = self.is_available()
        folder_count = 0
        file_count = 0
        if available:
            try:
                for entry in Path(watch_dir).iterdir():
                    if entry.is_dir() and not entry.name.startswith('.'):
                        folder_count += 1
                        for f in entry.iterdir():
                            if f.is_file() and _is_image(f.name):
                                file_count += 1
            except OSError:
                pass
        return {
            'enabled': bool(watch_dir),
            'connected': available,
            'watchDir': watch_dir,
            'foldersFound': folder_count,
            'filesFound': file_count,
        }

    def create_folder(self, project_code):
        """Create a project folder on the NAS mount. Returns the folder path."""
        watch_dir = self._watch_dir()
        if not watch_dir:
            return {'ok': False, 'error': 'NAS_WATCH_DIR not configured'}
        if not os.path.isdir(watch_dir):
            return {'ok': False, 'error': f'NAS mount not accessible: {watch_dir}'}

        folder_path = os.path.join(watch_dir, project_code)
        if os.path.isdir(folder_path):
            return {'ok': True, 'path': folder_path, 'existed': True}

        try:
            os.makedirs(folder_path, exist_ok=True)
            logger.info('[NAS] Created folder: %s', folder_path)
            return {'ok': True, 'path': folder_path, 'existed': False}
        except OSError as e:
            logger.error('[NAS] Failed to create folder %s: %s', folder_path, e)
            return {'ok': False, 'error': str(e)}

    def copy_file_to_project(self, local_file_path, project_code):
        """Copy a local file into the project folder on the NAS mount."""
        if not self.is_available():
            return {'ok': False, 'error': 'NAS mount not available'}

        folder_result = self.create_folder(project_code)
        if not folder_result.get('ok'):
            return folder_result

        folder_path = folder_result['path']
        filename = os.path.basename(local_file_path)
        dest = os.path.join(folder_path, filename)

        if os.path.exists(dest):
            base, ext = os.path.splitext(filename)
            import time
            dest = os.path.join(folder_path, f'{base}_{int(time.time())}{ext}')

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
        for entry in sorted(Path(watch_dir).iterdir()):
            if not entry.is_dir() or entry.name.startswith('.'):
                continue
            file_count = 0
            latest_mtime = 0
            for f in entry.iterdir():
                if f.is_file() and _is_image(f.name):
                    file_count += 1
                    mt = f.stat().st_mtime
                    if mt > latest_mtime:
                        latest_mtime = mt
            from datetime import datetime
            folders.append({
                'code': entry.name.upper(),
                'folderName': entry.name,
                'fileCount': file_count,
                'latestModified': datetime.utcfromtimestamp(latest_mtime).isoformat() if latest_mtime else None,
            })
        return folders

    def list_folder_files(self, project_code):
        """List image files in a specific project subfolder."""
        watch_dir = self._watch_dir()
        if not watch_dir:
            return []

        folder = Path(watch_dir) / project_code
        if not folder.is_dir():
            for d in Path(watch_dir).iterdir():
                if d.is_dir() and d.name.upper() == project_code.upper():
                    folder = d
                    break
            else:
                return []

        from datetime import datetime
        files = []
        for f in sorted(folder.iterdir()):
            if f.is_file() and _is_image(f.name):
                st = f.stat()
                files.append({
                    'name': f.name,
                    'size': st.st_size,
                    'modified': datetime.utcfromtimestamp(st.st_mtime).isoformat(),
                })
        return files


nas_mount = NasMountService()
