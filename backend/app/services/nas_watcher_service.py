"""NAS local-mount service — manages project folders on a mounted NAS share."""

import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services.project_number_match_service import (
    find_range_bucket_dir,
    is_range_folder_code,
    is_nas_bucket_dir_name,
    parse_nas_site_folder_code,
    parse_site_folder_code,
    pj_number_from_project_code,
)

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.bmp'}
PHOTO_SUBDIR = 'Photo'
_HK = ZoneInfo('Asia/Hong_Kong')
_DEFAULT_SCAN_MAX_DEPTH = 6


def _is_image(filename):
    return os.path.splitext(filename.lower())[1] in IMAGE_EXTENSIONS


def _path_has_hidden_part(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part.startswith('.') for part in rel.parts)


def _iter_project_images(folder: Path):
    """All image files under a project folder (any subfolder)."""
    for f in folder.rglob('*'):
        if not f.is_file() or not _is_image(f.name):
            continue
        if _path_has_hidden_part(f, folder):
            continue
        yield f


def _run_with_timeout(fn, timeout_s: float, default=None):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    if timeout_s <= 0:
        return fn()
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn)
        try:
            return fut.result(timeout=timeout_s)
        except FuturesTimeout:
            return default


class NasMountService:
    """Manages project folders on a locally-mounted NAS share (e.g. /Volumes/...)."""

    def __init__(self):
        self._app = None
        self._folder_cache: list = []
        self._folder_cache_at = 0.0
        self._cache_lock = threading.Lock()
        self._cache_stop = threading.Event()
        self._cache_thread: threading.Thread | None = None
        self._last_probe_ok = False
        self._last_probe_at = 0.0

    def init_app(self, app):
        self._app = app
        if not self.is_volume_mounted():
            watch = self._watch_dir()
            logger.warning(
                '[NAS] Local mount not found: %s — run backend/scripts/mount_nas_share.sh '
                '(use --via-tunnel on MacBook away from LAN)',
                watch or '(NAS_WATCH_DIR empty)',
            )
        self._start_folder_cache_loop()

    def _watch_dir(self):
        return self._app.config.get('NAS_WATCH_DIR', '') if self._app else ''

    def _resolved_watch_dir(self) -> str:
        """Filesystem NAS root: configured path, or share / inner folder under /Volumes."""
        configured = (self._watch_dir() or '').strip()
        if not configured:
            return ''
        path = Path(configured)
        if path.is_dir():
            return configured
        parts = path.parts
        if len(parts) < 3 or parts[1] != 'Volumes' or not parts[2]:
            return configured
        vol = Path('/', 'Volumes', parts[2])
        if not vol.is_dir():
            return configured
        inner = vol / 'Project Photo for Installation'
        if inner.is_dir():
            return str(inner)
        if os.path.ismount(vol):
            return str(vol)
        return configured

    def _scan_max_depth(self):
        if self._app:
            return int(self._app.config.get('NAS_SCAN_MAX_DEPTH', _DEFAULT_SCAN_MAX_DEPTH))
        return _DEFAULT_SCAN_MAX_DEPTH

    def _cfg(self, key, default):
        return self._app.config.get(key, default) if self._app else default

    def _io_timeout(self) -> float:
        return float(self._cfg('NAS_IO_TIMEOUT_S', 45))

    def _volume_mount_point(self) -> Path | None:
        watch = self._watch_dir()
        if not watch:
            return None
        parts = Path(watch).parts
        if len(parts) >= 3 and parts[1] == 'Volumes':
            return Path('/', 'Volumes', parts[2])
        return Path(watch)

    def is_volume_mounted(self) -> bool:
        """Fast check: SMB volume in mount table; local paths (tests) use isdir."""
        watch = self._watch_dir()
        if not watch:
            return False
        parts = Path(watch).parts
        if len(parts) >= 3 and parts[1] == 'Volumes':
            mp = self._volume_mount_point()
            if mp is None:
                return False
            try:
                return os.path.ismount(mp)
            except OSError:
                return False
        return os.path.isdir(watch)

    def probe_responsive(self, *, timeout_s: float | None = None) -> bool:
        """One cheap read on the watch dir; may hang on stale SMB — always time-boxed."""
        watch = self._resolved_watch_dir()
        if not watch or not self.is_volume_mounted():
            return False
        if timeout_s is None:
            timeout_s = float(self._cfg('NAS_PROBE_TIMEOUT_S', 4))

        def _probe():
            with os.scandir(watch) as it:
                next(it, None)
            return True

        ok = _run_with_timeout(_probe, timeout_s, default=False) is True
        self._last_probe_ok = ok
        self._last_probe_at = time.time()
        if not ok:
            logger.warning('[NAS] SMB probe timed out (%ss) for %s', timeout_s, watch)
        return ok

    def is_available(self, *, timeout_s: float = 5.0):
        if not self.is_volume_mounted():
            return False
        if self._cfg('NAS_FAST_CONNECT', True):
            return True
        return self.probe_responsive(timeout_s=timeout_s)

    def get_cached_folders(self, *, max_age_s: float | None = None):
        with self._cache_lock:
            cache = list(self._folder_cache)
            cache_at = self._folder_cache_at
        if max_age_s is None:
            max_age_s = float(self._cfg('NAS_FOLDER_CACHE_TTL_S', 600))
        if cache and (time.time() - cache_at) <= max_age_s:
            return cache
        return None

    def _set_folder_cache(self, folders: list) -> None:
        with self._cache_lock:
            self._folder_cache = folders
            self._folder_cache_at = time.time()

    def refresh_folder_cache(self) -> bool:
        if not self.is_volume_mounted():
            return False
        folders = _run_with_timeout(self.list_folders, self._io_timeout(), default=None)
        if folders is None:
            logger.warning('[NAS] Background folder cache refresh timed out')
            return False
        self._set_folder_cache(folders)
        logger.info('[NAS] Folder cache refreshed (%d site folders)', len(folders))
        return True

    def _start_folder_cache_loop(self):
        interval = int(self._cfg('NAS_FOLDER_CACHE_REFRESH_S', 300))
        if interval <= 0 or (self._cache_thread and self._cache_thread.is_alive()):
            return
        app = self._app

        def _loop():
            while not self._cache_stop.wait(interval):
                if not app:
                    continue
                with app.app_context():
                    if self.is_volume_mounted():
                        self.probe_responsive()
                        self.refresh_folder_cache()

        self._cache_stop.clear()
        self._cache_thread = threading.Thread(target=_loop, daemon=True, name='nas-folder-cache')
        self._cache_thread.start()

    def status(self):
        configured = (self._watch_dir() or '').strip()
        watch_dir = self._resolved_watch_dir()
        mounted = self.is_volume_mounted()
        connected = mounted
        cached = self.get_cached_folders() or []
        cache_age = int(time.time() - self._folder_cache_at) if self._folder_cache_at else None
        ttl = int(self._cfg('NAS_FOLDER_CACHE_TTL_S', 600))
        degraded = mounted and self._last_probe_at > 0 and not self._last_probe_ok
        if mounted and not cached and not self._folder_cache_at:
            threading.Thread(target=self.refresh_folder_cache, daemon=True).start()

        out = {
            'enabled': bool(configured or watch_dir),
            'connected': connected,
            'degraded': degraded,
            'watchDir': configured or watch_dir,
            'foldersFound': len(cached),
            'foldersCacheAgeSec': cache_age,
            'filesFound': 0,
        }
        if watch_dir and not mounted:
            out['disconnectReason'] = 'mount_missing'
            out['mountHint'] = (
                'Mount the SMB share so this folder exists (Mac Mini: Finder; '
                'MacBook: ./scripts/mount_nas_share.sh --via-tunnel).'
            )
        elif mounted and degraded:
            out['mountHint'] = (
                'SMB is slow or stale. Remount: backend/scripts/mount_nas_share.sh --via-tunnel'
            )
        if mounted:
            out['rootFolderNames'] = self.list_watch_root_dir_names()
        else:
            out['rootFolderNames'] = []
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

    def _resolve_parent_dir(self, parent_key):
        """Parent directory for nested create (site folder, range bucket, or top-level name)."""
        key = (parent_key or '').strip()
        if not key:
            return None
        hit = self._resolve_project_folder(key)
        if hit is not None:
            return hit
        return self._resolve_bucket_dir(key)

    def _resolve_bucket_dir(self, bucket_code):
        """NAS directory for a range bucket or top-level folder (e.g. PJ-2800-2899, ABC)."""
        watch_dir = self._resolved_watch_dir()
        if not watch_dir:
            return None
        key = (bucket_code or '').strip()
        if not key:
            return None
        root = Path(watch_dir)
        if not root.is_dir():
            return None
        direct = root / key
        if direct.is_dir():
            return direct
        key_u = key.upper()
        try:
            for entry in root.iterdir():
                if entry.is_dir() and not entry.name.startswith('.') and entry.name.upper() == key_u:
                    return entry
        except OSError:
            return None
        return None

    def create_folder(self, project_code, *, parent_bucket_code=None, skip_deep_resolve=False):
        """Create a project folder on the NAS mount. Returns the folder path."""
        watch_dir = self._resolved_watch_dir()
        if not watch_dir:
            return {'ok': False, 'error': 'NAS_WATCH_DIR not configured'}
        if not os.path.isdir(watch_dir):
            return {'ok': False, 'error': f'NAS mount not accessible: {watch_dir}'}

        code = (project_code or '').strip()
        parent_key = (parent_bucket_code or '').strip() or None
        parent_dir = self._resolve_parent_dir(parent_key) if parent_key else None
        if parent_key and parent_dir is None:
            root = Path(watch_dir)
            parent_dir = root / parent_key
            try:
                os.makedirs(parent_dir, exist_ok=True)
                logger.info('[NAS] Created parent folder for nested project: %s', parent_dir)
            except OSError as e:
                return {
                    'ok': False,
                    'error': f'Parent folder "{parent_key}" not on NAS and could not be created: {e}',
                }

        if parent_dir is not None:
            folder_path = parent_dir / code
            if folder_path.is_dir():
                return {'ok': True, 'path': str(folder_path), 'existed': True}
        else:
            root = Path(watch_dir)
            direct = root / code
            if direct.is_dir():
                return {'ok': True, 'path': str(direct), 'existed': True}
            if not skip_deep_resolve:
                existing = self._resolve_project_folder(project_code)
                if existing is not None:
                    return {'ok': True, 'path': str(existing), 'existed': True}
            pj_num = pj_number_from_project_code(code)
            bucket = find_range_bucket_dir(watch_dir, pj_num) if pj_num is not None else None
            if bucket is not None:
                folder_path = bucket / code
            else:
                folder_path = direct
        try:
            os.makedirs(folder_path, exist_ok=True)
            logger.info('[NAS] Created folder: %s', folder_path)
            return {'ok': True, 'path': str(folder_path), 'existed': False}
        except OSError as e:
            logger.error('[NAS] Failed to create folder %s: %s', folder_path, e)
            return {'ok': False, 'error': str(e)}

    def _hk_today_str(self):
        return datetime.now(_HK).date().isoformat()

    def _project_folder_from_mongo(self, project_code):
        """Fast path: nested site folders via nasParentBucket (avoid SMB deep scan)."""
        from app import mongo

        code = (project_code or '').strip()
        if not code:
            return None
        doc = mongo.db.wa_projects.find_one({
            'code': {'$regex': f'^{re.escape(code)}$', '$options': 'i'},
            'status': {'$ne': 'archived'},
        })
        if not doc:
            return None
        parent = (doc.get('nasParentBucket') or '').strip()
        bucket = self._resolve_bucket_dir(parent) if parent else None
        if bucket is not None:
            folder_label = (doc.get('nasFolderName') or '').strip() or code
            for name in (folder_label, code):
                site = bucket / name
                if site.is_dir():
                    return site
        nf = (doc.get('nasFolder') or '').strip()
        if nf and os.path.isdir(nf):
            return Path(nf)
        return None

    def ensure_photo_day_dir(self, project_code, day_str=None):
        """Project folder / Photo / YYYY-MM-DD (matches manual NAS layout)."""
        if not self.is_available():
            return None
        day = day_str or self._hk_today_str()
        proj = self._resolve_project_folder(project_code)
        if proj is None:
            parent = None
            from app import mongo
            doc = mongo.db.wa_projects.find_one({
                'code': {'$regex': f'^{re.escape((project_code or "").strip())}$', '$options': 'i'},
            })
            if doc:
                parent = (doc.get('nasParentBucket') or '').strip() or None
            created = self.create_folder(
                project_code,
                parent_bucket_code=parent,
                skip_deep_resolve=True,
            )
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

    def list_watch_root_dir_names(self, *, timeout_s: float | None = None):
        """Fast top-level folder names under NAS_WATCH_DIR (no deep scan)."""
        watch = self._resolved_watch_dir()
        if not watch or not os.path.isdir(watch):
            return []

        def _read():
            return sorted(
                e.name
                for e in os.scandir(watch)
                if e.is_dir() and not e.name.startswith('.')
            )

        if timeout_s is None:
            timeout_s = float(self._cfg('NAS_PROBE_TIMEOUT_S', 4))
        return _run_with_timeout(_read, timeout_s, default=[]) or []

    def list_folders_for_api(self):
        """Cached site-folder list for list views / sync index (never blocks for full SMB walk)."""
        cached = self.get_cached_folders()
        if cached is not None:
            return cached
        return _run_with_timeout(self.list_folders, self._io_timeout(), default=[]) or []

    def list_folders(self):
        """List site project folders (recursive through range buckets, not into projects)."""
        watch_dir = self._resolved_watch_dir()
        if not watch_dir or not os.path.isdir(watch_dir):
            return []

        max_depth = self._scan_max_depth()
        folders = []
        seen_codes = set()
        root = Path(watch_dir)

        def walk(parent: Path, depth: int, parent_bucket: str | None):
            if depth > max_depth:
                return
            try:
                entries = sorted(parent.iterdir())
            except OSError as e:
                logger.warning('[NAS] list_folders iterdir failed under %s: %s', parent, e)
                return
            for entry in entries:
                if not entry.is_dir() or entry.name.startswith('.'):
                    continue
                if is_nas_bucket_dir_name(entry.name):
                    walk(entry, depth + 1, entry.name)
                    continue
                site_code = parse_nas_site_folder_code(entry.name)
                if site_code:
                    code_key = site_code.upper()
                    if code_key not in seen_codes:
                        seen_codes.add(code_key)
                        folders.append({
                            'code': site_code,
                            'folderName': entry.name,
                            'parentBucket': parent_bucket,
                            'fileCount': 0,
                            'latestModified': None,
                        })
                    continue
                walk(entry, depth + 1, parent_bucket)

        walk(root, 0, None)
        return folders

    def _resolve_project_folder(self, project_code):
        watch_dir = self._resolved_watch_dir()
        if not watch_dir:
            return None
        root = Path(watch_dir)
        if not root.is_dir():
            return None

        fast = self._project_folder_from_mongo(project_code)
        if fast is not None:
            return fast

        direct = root / project_code
        if direct.is_dir():
            return direct

        max_depth = self._scan_max_depth()

        def find_under(parent: Path, depth: int):
            if depth > max_depth:
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

    def _list_bucket_child_folders_sync(self, range_code):
        code = (range_code or '').strip()
        if not (is_range_folder_code(code) or is_nas_bucket_dir_name(code)):
            return []
        bucket = self._resolve_bucket_dir(code)
        if bucket is None or not bucket.is_dir():
            return []
        out = []
        try:
            for entry in sorted(bucket.iterdir()):
                if not entry.is_dir() or entry.name.startswith('.'):
                    continue
                site_code = parse_nas_site_folder_code(entry.name)
                out.append({
                    'folderName': entry.name,
                    'code': site_code,
                    'isSiteProject': site_code is not None,
                })
        except OSError as e:
            logger.warning('[NAS] list_bucket_child_folders failed: %s', e)
        return out

    def list_bucket_child_folders(self, range_code):
        """All direct child directories under a bucket (PJ-lo-hi, T-lo-hi, …)."""
        timeout = min(float(self._cfg('NAS_PROBE_TIMEOUT_S', 4)) * 3, 30.0)
        result = _run_with_timeout(
            lambda: self._list_bucket_child_folders_sync(range_code),
            timeout,
            default=None,
        )
        if result is None:
            logger.warning('[NAS] list_bucket_child_folders timed out for %s', range_code)
            return []
        return result

    def list_bucket_site_folders(self, range_code):
        """Site project directories that are direct children of a PJ-lo-hi bucket."""
        return [
            {'code': f['code'], 'folderName': f['folderName']}
            for f in self.list_bucket_child_folders(range_code)
            if f.get('code')
        ]

    def list_project_subfolders(self, project_code):
        """Immediate subdirectories under a site project folder."""
        folder = self._resolve_project_folder(project_code)
        if not folder:
            return []
        out = []
        try:
            for entry in sorted(folder.iterdir()):
                if entry.is_dir() and not entry.name.startswith('.'):
                    out.append({'name': entry.name})
        except OSError as e:
            logger.warning('[NAS] list_project_subfolders failed: %s', e)
        return out

    def list_loose_root_files(self, project_code):
        """Image files sitting directly on a folder root (not in subdirs)."""
        folder = self._resolve_project_folder(project_code)
        if not folder:
            return []
        files = []
        try:
            for f in sorted(folder.iterdir()):
                if not f.is_file() or not _is_image(f.name):
                    continue
                st = f.stat()
                files.append({
                    'name': f.name,
                    'size': st.st_size,
                    'modified': datetime.utcfromtimestamp(st.st_mtime).isoformat(),
                    'relativePath': f.name,
                    'absolutePath': str(f),
                })
        except OSError as e:
            logger.warning('[NAS] list_loose_root_files failed: %s', e)
        return files

    def _folder_stats_sync(self, project_code):
        if is_range_folder_code(project_code):
            bucket = self._resolve_project_folder(project_code)
            if not bucket:
                return None
            sites = self.list_bucket_site_folders(project_code)
            return {
                'code': project_code.upper(),
                'folderName': bucket.name,
                'fileCount': 0,
                'siteFolderCount': len(sites),
                'latestModified': None,
            }
        folder = self._resolve_project_folder(project_code)
        if not folder:
            return None
        file_count = 0
        latest_mtime = 0
        for f in _iter_project_images(folder):
            file_count += 1
            mt = f.stat().st_mtime
            if mt > latest_mtime:
                latest_mtime = mt
        canonical = parse_site_folder_code(folder.name) or folder.name.upper()
        return {
            'code': canonical,
            'folderName': folder.name,
            'fileCount': file_count,
            'latestModified': datetime.utcfromtimestamp(latest_mtime).isoformat() if latest_mtime else None,
        }

    def folder_stats(self, project_code):
        """Stats for one project folder only (time-boxed — no unbounded SMB walk on API thread)."""
        return _run_with_timeout(
            lambda: self._folder_stats_sync(project_code),
            self._io_timeout(),
            default=None,
        )

    def _unlink_with_retry(self, p: Path, *, attempts: int = 5) -> None:
        last_err = None
        for i in range(attempts):
            try:
                p.unlink()
                return
            except OSError as e:
                last_err = e
                if i + 1 < attempts:
                    time.sleep(0.25 * (i + 1))
        if last_err:
            raise last_err

    def _rmtree_smb(self, target: Path) -> None:
        """Bottom-up delete (SMB rmtree often returns EBUSY)."""
        if not target.is_dir():
            self._unlink_with_retry(target)
            return
        for entry in list(target.iterdir()):
            if entry.is_dir():
                self._rmtree_smb(entry)
            else:
                self._unlink_with_retry(entry)
        last_err = None
        for i in range(6):
            try:
                target.rmdir()
                return
            except OSError as e:
                last_err = e
                if e.errno == 16:  # EBUSY — Finder / SMB cache
                    time.sleep(0.4 * (i + 1))
                    continue
                raise
        if last_err:
            raise last_err

    def delete_path(self, path):
        """Delete a file or folder under NAS_WATCH_DIR (no-op if already missing)."""
        watch_dir = self._resolved_watch_dir()
        if not watch_dir or not path:
            return {'ok': False, 'error': 'NAS not configured'}
        try:
            watch = Path(watch_dir).resolve()
            target = Path(path).resolve()
            if not str(target).startswith(str(watch)):
                return {'ok': False, 'error': 'Path outside NAS watch directory'}
            if not target.exists():
                return {'ok': True, 'missing': True}

            def _do_delete():
                if target.is_dir():
                    self._rmtree_smb(target)
                else:
                    self._unlink_with_retry(target)

            err = _run_with_timeout(_do_delete, self._io_timeout(), default='timeout')
            if err == 'timeout':
                return self._quarantine_folder(target)
            logger.info('[NAS] Deleted %s', target)
            self._folder_cache_at = 0.0
            return {'ok': True}
        except OSError as e:
            logger.warning('[NAS] Delete failed %s: %s', path, e)
            if getattr(e, 'errno', None) == 16 and target.is_dir():
                return self._quarantine_folder(target)
            return {'ok': False, 'error': str(e)}

    def _quarantine_folder(self, target: Path):
        """SMB often blocks rmtree (EBUSY / .smbdelete*); hide folder via rename."""
        if not target.is_dir():
            return {'ok': False, 'error': 'Delete failed (resource busy)'}
        stamp = int(time.time())
        dest = target.parent / f'.trash-{target.name}-{stamp}'
        try:
            shutil.move(str(target), str(dest))
            logger.info('[NAS] Quarantined %s → %s', target.name, dest.name)
            self._folder_cache_at = 0.0
            return {
                'ok': True,
                'quarantined': True,
                'path': str(dest),
                'message': (
                    f'Folder moved to {dest.name} (SMB locked some files). '
                    'Remove it in Synology File Station if needed.'
                ),
            }
        except OSError as e:
            return {
                'ok': False,
                'error': (
                    f'{e} — close Finder windows for this folder, or delete via Synology DSM.'
                ),
            }

    def delete_project_folder(self, project_code):
        folder = self._resolve_project_folder(project_code)
        if not folder:
            return {'ok': True, 'missing': True}
        return self.delete_path(str(folder))

    def rename_bucket_folder(self, bucket_code, new_dir_name):
        """Rename a top-level NAS bucket directory (PJ-lo-hi, T-lo-hi, ABC, …)."""
        new_dir_name = (new_dir_name or '').strip()
        if not new_dir_name or new_dir_name.startswith('.'):
            return {'ok': False, 'error': 'Invalid folder name'}
        folder = self._resolve_bucket_dir(bucket_code)
        if folder is None or not folder.is_dir():
            return {'ok': False, 'error': 'NAS bucket folder not found'}
        dest = folder.parent / new_dir_name
        if dest.resolve() == folder.resolve():
            return {'ok': True, 'path': str(folder), 'existed': True}
        if dest.exists():
            return {'ok': False, 'error': f'Folder already exists: {new_dir_name}'}
        try:
            shutil.move(str(folder), str(dest))
            logger.info('[NAS] Renamed bucket %s → %s', folder.name, new_dir_name)
            return {'ok': True, 'path': str(dest)}
        except OSError as e:
            logger.warning('[NAS] Bucket rename failed %s: %s', folder, e)
            return {'ok': False, 'error': str(e)}

    def rename_site_folder(self, project_code, new_dir_name, *, parent_bucket_code=None):
        """Rename a site project directory on NAS (Web → NAS)."""
        new_dir_name = (new_dir_name or '').strip()
        if not new_dir_name or new_dir_name.startswith('.'):
            return {'ok': False, 'error': 'Invalid folder name'}

        folder = self._resolve_project_folder(project_code)
        if folder is None and parent_bucket_code:
            parent = self._resolve_bucket_dir(parent_bucket_code)
            if parent is not None:
                folder = parent / project_code
                if not folder.is_dir():
                    folder = None
        if folder is None or not folder.is_dir():
            return {'ok': False, 'error': 'NAS folder not found'}

        dest = folder.parent / new_dir_name
        if dest.resolve() == folder.resolve():
            return {'ok': True, 'path': str(folder), 'existed': True}
        if dest.exists():
            return {'ok': False, 'error': f'Folder already exists: {new_dir_name}'}

        try:
            shutil.move(str(folder), str(dest))
            logger.info('[NAS] Renamed %s → %s', folder.name, new_dir_name)
            return {'ok': True, 'path': str(dest)}
        except OSError as e:
            logger.warning('[NAS] Rename failed %s: %s', folder, e)
            return {'ok': False, 'error': str(e)}

    def _list_folder_files_sync(self, project_code):
        folder = self._resolve_project_folder(project_code)
        if not folder:
            return []

        files = []
        seen = set()
        for f in sorted(_iter_project_images(folder), key=lambda p: str(p)):
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
                'absolutePath': str(f),
            })
        return files

    def list_folder_files(self, project_code):
        """List image files under the project folder (all subfolders, time-boxed)."""
        result = _run_with_timeout(
            lambda: self._list_folder_files_sync(project_code),
            self._io_timeout(),
            default=None,
        )
        if result is None:
            logger.warning('[NAS] list_folder_files timed out for %s', project_code)
            return []
        return result


nas_mount = NasMountService()
