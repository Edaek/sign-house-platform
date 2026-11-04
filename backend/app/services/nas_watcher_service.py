"""NAS local-mount service — manages project folders on a mounted NAS share."""
from __future__ import annotations

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


def _iter_project_remark_txt(folder: Path):
    """Site remark .txt under Photo/YYYY-MM-DD/ (fast on SMB); then legacy paths."""
    seen: set[str] = set()
    photo = folder / PHOTO_SUBDIR
    if photo.is_dir():
        try:
            for day_dir in sorted(photo.iterdir(), key=lambda p: p.name):
                if not day_dir.is_dir() or day_dir.name.startswith('.'):
                    continue
                if _path_has_hidden_part(day_dir, folder):
                    continue
                try:
                    for f in sorted(day_dir.glob('*.txt'), key=lambda p: p.name):
                        if not f.is_file() or f.name.startswith('.'):
                            continue
                        key = str(f.resolve())
                        if key in seen:
                            continue
                        seen.add(key)
                        yield f
                except OSError:
                    continue
        except OSError as e:
            logger.warning('[NAS] list Photo day txt failed under %s: %s', folder, e)
    try:
        for f in sorted(folder.rglob('*.txt'), key=lambda p: str(p)):
            if not f.is_file() or f.name.startswith('.'):
                continue
            if _path_has_hidden_part(f, folder):
                continue
            key = str(f.resolve())
            if key in seen:
                continue
            seen.add(key)
            yield f
    except OSError as e:
        logger.warning('[NAS] rglob txt failed under %s: %s', folder, e)


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
        self._bucket_children_cache: dict[str, list] = {}
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

    def peek_folder_cache(self):
        """Last folder list from NAS (ignores TTL) — for fast list labels."""
        with self._cache_lock:
            if not self._folder_cache:
                return None
            return list(self._folder_cache)

    def _set_folder_cache(self, folders: list) -> None:
        with self._cache_lock:
            self._folder_cache = folders
            self._folder_cache_at = time.time()

    def _folder_cache_io_timeout_s(self) -> float:
        """Background full-tree scan may exceed normal NAS_IO_TIMEOUT_S on slow SMB."""
        base = self._io_timeout()
        extra = float(self._cfg('NAS_FOLDER_CACHE_IO_TIMEOUT_S', 120))
        return max(base, extra)

    def refresh_folder_cache(self) -> bool:
        if not self.is_volume_mounted():
            return False
        timeout_s = self._folder_cache_io_timeout_s()
        folders = _run_with_timeout(self.list_folders, timeout_s, default=None)
        if folders is None:
            stale = self.peek_folder_cache()
            if stale:
                logger.info(
                    '[NAS] Background folder cache refresh timed out (%ss) — keeping %d cached folder(s)',
                    int(timeout_s),
                    len(stale),
                )
            else:
                logger.warning(
                    '[NAS] Background folder cache refresh timed out (%ss); NAS list may be empty until remount or retry',
                    int(timeout_s),
                )
            return False
        self._set_folder_cache(folders)
        self._refresh_bucket_children_caches()
        logger.info('[NAS] Folder cache refreshed (%d site folders)', len(folders))
        return True

    def _set_bucket_children_cache_entry(self, bucket_code: str, children: list) -> None:
        key = (bucket_code or '').strip().lower()
        if not key:
            return
        with self._cache_lock:
            self._bucket_children_cache[key] = list(children)

    def peek_bucket_children_cache(self, range_code: str):
        """Full child folder list for one range bucket (no SMB)."""
        from app.services.nas_bucket_code import bucket_lookup_keys

        for key in bucket_lookup_keys(range_code):
            with self._cache_lock:
                rows = self._bucket_children_cache.get(key)
            if rows:
                return list(rows)
        return None

    def refresh_bucket_children_cache_for(self, range_code: str) -> bool:
        """Time-boxed SMB scan for one bucket → updates in-memory bucket cache."""
        code = (range_code or '').strip()
        if not code:
            return False
        children = self.list_bucket_child_folders(code)
        if children:
            from app.services.nas_bucket_code import bucket_lookup_keys

            for cache_key in bucket_lookup_keys(code):
                self._set_bucket_children_cache_entry(cache_key, children)
            logger.info('[NAS] Bucket children cache updated for %s (%d folders)', code, len(children))
            return True
        return False

    def _refresh_bucket_children_caches(self) -> None:
        """Populate per-bucket child lists (all physical folders, not deduped by site code)."""
        from app.services.nas_sync_service import _is_nas_root_bucket_dir

        root_names = self.list_watch_root_dir_names(timeout_s=8) or []
        refreshed = 0
        for name in root_names:
            if not _is_nas_root_bucket_dir(name):
                continue
            if self.refresh_bucket_children_cache_for(name):
                refreshed += 1
        if refreshed:
            logger.info('[NAS] Bucket children cache updated for %d range folder(s)', refreshed)

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
        folders_cache_stale = False
        if mounted:
            if not cached:
                folders_cache_stale = True
            elif cache_age is not None and cache_age > ttl:
                folders_cache_stale = True
        out['foldersCacheStale'] = folders_cache_stale
        mongo_active = 0
        try:
            from app import mongo

            mongo_active = mongo.db.wa_projects.count_documents({'status': {'$ne': 'archived'}})
        except Exception:
            pass
        out['mongoActiveProjects'] = mongo_active
        # Do not scandir SMB on /nas/status — dev Flask is single-threaded; use cache only.
        out['rootFolderNames'] = []
        if mounted and cached:
            buckets = sorted({
                (row.get('parentBucket') or '').strip()
                for row in cached
                if (row.get('parentBucket') or '').strip()
            })
            if buckets:
                out['rootFolderNames'] = buckets
        from app.services.loomy_wa_nas_summary import format_wa_nas_summary_zh

        out['statusSummaryZh'] = format_wa_nas_summary_zh(out)
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
        from app.services.nas_bucket_code import nas_path_from_web_bucket

        key = nas_path_from_web_bucket(parent_key)
        if not key:
            return None
        hit = self._resolve_project_folder(key)
        if hit is not None:
            return hit
        return self._resolve_bucket_dir(key)

    def _resolve_bucket_dir(self, bucket_code):
        """NAS directory for a range bucket or top-level folder (e.g. PJ-2800-2899, ABC)."""
        from app.services.nas_bucket_code import nas_path_from_web_bucket

        watch_dir = self._resolved_watch_dir()
        if not watch_dir:
            return None
        key = nas_path_from_web_bucket(bucket_code)
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
        if bucket is not None and bucket.is_dir():
            matches = []
            try:
                for entry in bucket.iterdir():
                    if entry.is_dir() and not entry.name.startswith('.'):
                        if self._matches_project_dir_name(entry.name, code):
                            matches.append(entry)
            except OSError:
                matches = []
            if matches:
                return max(matches, key=lambda p: len(p.name))
        nf = (doc.get('nasFolder') or '').strip()
        if nf and os.path.isdir(nf):
            return Path(nf)
        return None

    def _find_dir_named(self, parent: Path, folder_name: str):
        pref = (folder_name or '').strip()
        if not pref or parent is None or not parent.is_dir():
            return None
        exact = parent / pref
        if exact.is_dir():
            return exact
        try:
            for entry in parent.iterdir():
                if entry.is_dir() and entry.name.strip() == pref:
                    return entry
        except OSError:
            return None
        return None

    def _resolve_site_folder_path(
        self,
        project_code,
        *,
        preferred_folder_name=None,
        preferred_parent_bucket=None,
    ):
        """Exact NAS folder name wins; never fall back to longest-name match when pref was given."""
        pref = (preferred_folder_name or '').strip()
        if pref:
            from app import mongo

            parent_keys = []
            pb = (preferred_parent_bucket or '').strip()
            if pb:
                parent_keys.append(pb)
            doc = mongo.db.wa_projects.find_one({
                'code': {'$regex': f'^{re.escape((project_code or "").strip())}$', '$options': 'i'},
            })
            mongo_parent = (doc.get('nasParentBucket') or '').strip() if doc else ''
            if mongo_parent and mongo_parent not in parent_keys:
                parent_keys.append(mongo_parent)

            watch = self._resolved_watch_dir()
            if watch:
                root = Path(watch)
                for name in self.list_watch_root_dir_names() or []:
                    if is_nas_bucket_dir_name(name) and name not in parent_keys:
                        parent_keys.append(name)
                tried = set()
                for key in parent_keys:
                    if not key or key in tried:
                        continue
                    tried.add(key)
                    bucket = self._resolve_bucket_dir(key)
                    if bucket is not None:
                        hit = self._find_dir_named(bucket, pref)
                        if hit is not None:
                            return hit
                hit = self._find_dir_named(root, pref)
                if hit is not None:
                    return hit
            logger.warning(
                '[NAS] Preferred folder %r not found for %s (buckets=%s)',
                pref,
                project_code,
                parent_keys[:5],
            )
            return None
        return self._resolve_project_folder(project_code)

    def _folder_for_project(
        self,
        project_code,
        project_doc=None,
        *,
        folder_name=None,
        parent_bucket=None,
    ):
        """Resolve NAS site directory — prefer stored/query folder name over longest match."""
        fn = (folder_name or '').strip()
        pb = (parent_bucket or '').strip()
        if project_doc:
            fn = fn or (project_doc.get('nasFolderName') or '').strip()
            pb = pb or (project_doc.get('nasParentBucket') or '').strip()
        if fn:
            hit = self._resolve_site_folder_path(
                project_code,
                preferred_folder_name=fn,
                preferred_parent_bucket=pb or None,
            )
            if hit is not None:
                return hit
        return self._resolve_project_folder(project_code)

    def ensure_photo_day_dir(
        self,
        project_code,
        day_str=None,
        *,
        preferred_folder_name=None,
        preferred_parent_bucket=None,
    ):
        """Project folder / Photo / YYYY-MM-DD (matches manual NAS layout)."""
        if not self.is_available():
            return None
        day = day_str or self._hk_today_str()
        proj = self._resolve_site_folder_path(
            project_code,
            preferred_folder_name=preferred_folder_name,
            preferred_parent_bucket=preferred_parent_bucket,
        )
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

    def resolve_photo_day_dir(
        self,
        project_code,
        day_str=None,
        *,
        preferred_folder_name=None,
        preferred_parent_bucket=None,
    ):
        """Existing Photo/YYYY-MM-DD only — never creates project or day folders."""
        if not self.is_available():
            return None
        day = day_str or self._hk_today_str()
        proj = self._resolve_site_folder_path(
            project_code,
            preferred_folder_name=preferred_folder_name,
            preferred_parent_bucket=preferred_parent_bucket,
        )
        if proj is None:
            return None
        day_dir = proj / PHOTO_SUBDIR / day
        if not day_dir.is_dir():
            return None
        return str(day_dir)

    def copy_file_to_project(
        self,
        local_file_path,
        project_code,
        *,
        day_str=None,
        preferred_folder_name=None,
        preferred_parent_bucket=None,
    ):
        """Copy a local file into Photo/YYYY-MM-DD under the project folder."""
        if not self.is_available():
            return {'ok': False, 'error': 'NAS mount not available'}

        day_dir = self.ensure_photo_day_dir(
            project_code,
            day_str,
            preferred_folder_name=preferred_folder_name,
            preferred_parent_bucket=preferred_parent_bucket,
        )
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
        by_code: dict = {}
        root = Path(watch_dir)

        def _keep_site_row(site_code, folder_name, parent_bucket):
            key = (site_code or '').upper()
            if not key:
                return
            row = {
                'code': site_code,
                'folderName': folder_name,
                'parentBucket': parent_bucket,
                'fileCount': 0,
                'latestModified': None,
            }
            prev = by_code.get(key)
            if prev is None or len(folder_name) > len(prev.get('folderName') or ''):
                by_code[key] = row

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
                    _keep_site_row(site_code, entry.name, parent_bucket)
                    continue
                walk(entry, depth + 1, parent_bucket)

        walk(root, 0, None)
        return list(by_code.values())

    def nas_folder_display_name(self, project_code, *, parent_bucket=None, project_doc=None):
        """Best-effort NAS directory label (includes site remark after PJ-xxxx)."""
        code = (project_code or '').strip()
        if not code:
            return ''
        parent = (parent_bucket or '').strip()
        if not parent and project_doc:
            parent = (project_doc.get('nasParentBucket') or '').strip()
        bucket = self._resolve_bucket_dir(parent) if parent else None
        if bucket is not None and bucket.is_dir():
            matches = []
            try:
                for entry in bucket.iterdir():
                    if entry.is_dir() and not entry.name.startswith('.'):
                        if self._matches_project_dir_name(entry.name, code):
                            matches.append(entry.name)
            except OSError:
                matches = []
            if matches:
                return max(matches, key=len)
        folder = self._resolve_project_folder(code)
        return folder.name if folder is not None else code

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
            bucket_hits = [
                d for d in children
                if self._matches_project_dir_name(d.name, project_code)
            ]
            if bucket_hits:
                return max(bucket_hits, key=lambda p: len(p.name))
            for d in children:
                hit = find_under(d, depth + 1)
                if hit is not None:
                    return hit
            return None

        return find_under(root, 0)

    def _list_bucket_child_folders_sync(self, range_code):
        from app.services.nas_bucket_code import nas_path_from_web_bucket

        code = nas_path_from_web_bucket(range_code)
        if not code:
            return []
        bucket = self._resolve_bucket_dir(code)
        if bucket is None or not bucket.is_dir():
            return []
        out = []
        root_bucket_names = {
            n.upper()
            for n in (self.list_watch_root_dir_names(timeout_s=4) or [])
        }
        try:
            for entry in sorted(bucket.iterdir()):
                if not entry.is_dir() or entry.name.startswith('.'):
                    continue
                if (
                    root_bucket_names
                    and entry.name.upper() in root_bucket_names
                    and code.upper() != entry.name.upper()
                ):
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

    def bucket_child_folders_from_cache(self, range_code):
        """Site folders under one bucket from the background folder cache (no SMB)."""
        bucket = (range_code or '').strip()
        if not bucket:
            return []
        direct = self.peek_bucket_children_cache(bucket)
        if direct:
            return direct
        cached = self.peek_folder_cache() or self.get_cached_folders(max_age_s=86400) or []
        if not cached:
            return []
        from app.services.nas_bucket_code import bucket_lookup_keys

        bucket_keys = set(bucket_lookup_keys(bucket))
        out = []
        for row in cached:
            parent = (row.get('parentBucket') or '').strip().lower()
            if parent not in bucket_keys:
                continue
            folder_name = (row.get('folderName') or '').strip()
            if not folder_name:
                continue
            code = (row.get('code') or '').strip() or None
            out.append({
                'folderName': folder_name,
                'code': code,
                'isSiteProject': code is not None,
            })
        out.sort(key=lambda c: (c.get('folderName') or '').lower())
        return out

    def list_bucket_child_folders_with_fallback(self, range_code):
        """Live SMB listing (time-boxed), then stale cache if live is empty."""
        live = self.list_bucket_child_folders(range_code)
        if live:
            return live, False
        cached = self.bucket_child_folders_from_cache(range_code)
        if cached:
            logger.info('[NAS] bucket %s: using cached folder list (%s rows)', range_code, len(cached))
        return cached, bool(cached)

    def list_bucket_site_folders(self, range_code):
        """Site project directories that are direct children of a PJ-lo-hi bucket."""
        return [
            {'code': f['code'], 'folderName': f['folderName']}
            for f in self.list_bucket_child_folders(range_code)
            if f.get('code')
        ]

    def _list_project_subfolders_sync(
        self,
        project_code,
        *,
        project_doc=None,
        folder_name=None,
        parent_bucket=None,
    ):
        folder = self._folder_for_project(
            project_code,
            project_doc,
            folder_name=folder_name,
            parent_bucket=parent_bucket,
        )
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

    def list_project_subfolders(self, project_code, *, project_doc=None, folder_name=None, parent_bucket=None):
        """Immediate subdirectories under a site project folder (time-boxed SMB)."""
        doc = project_doc
        fn = folder_name
        pb = parent_bucket
        result = _run_with_timeout(
            lambda: self._list_project_subfolders_sync(
                project_code,
                project_doc=doc,
                folder_name=fn,
                parent_bucket=pb,
            ),
            self._io_timeout(),
            default=None,
        )
        if result is None:
            logger.warning('[NAS] list_project_subfolders timed out for %s', project_code)
            return []
        return result

    def list_loose_root_files(self, project_code, *, project_doc=None, folder_name=None, parent_bucket=None):
        """Image files sitting directly on a folder root (not in subdirs)."""
        folder = self._folder_for_project(
            project_code,
            project_doc,
            folder_name=folder_name,
            parent_bucket=parent_bucket,
        )
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

    def _folder_stats_sync(
        self,
        project_code,
        *,
        project_doc=None,
        folder_name=None,
        parent_bucket=None,
    ):
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
        folder = self._folder_for_project(
            project_code,
            project_doc,
            folder_name=folder_name,
            parent_bucket=parent_bucket,
        )
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

    def folder_stats(
        self,
        project_code,
        *,
        project_doc=None,
        folder_name=None,
        parent_bucket=None,
    ):
        """Stats for one project folder only (time-boxed — no unbounded SMB walk on API thread)."""
        doc = project_doc
        fn = folder_name
        pb = parent_bucket
        return _run_with_timeout(
            lambda: self._folder_stats_sync(
                project_code,
                project_doc=doc,
                folder_name=fn,
                parent_bucket=pb,
            ),
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

    def delete_project_folder(self, project_code, *, project_doc=None):
        folder = self._folder_for_project(project_code, project_doc)
        if folder is None:
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

    _NAS_IMAGE_SUFFIXES = frozenset({
        '.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.bmp',
    })

    def _resolve_project_relative_file(
        self,
        project_code,
        relative_path,
        *,
        allowed_suffixes=None,
        project_doc=None,
        folder_name=None,
        parent_bucket=None,
    ):
        folder = self._folder_for_project(
            project_code,
            project_doc,
            folder_name=folder_name,
            parent_bucket=parent_bucket,
        )
        if folder is None:
            return None, None
        root = folder.resolve()
        rel = (relative_path or '').strip().replace('\\', '/').lstrip('/')
        if not rel or '..' in rel.split('/'):
            return None, None
        target = (folder / rel).resolve()
        if not str(target).startswith(str(root)):
            return None, None
        if allowed_suffixes is not None and target.suffix.lower() not in allowed_suffixes:
            return None, None
        return root, target

    def _resolve_project_txt_path(
        self,
        project_code,
        relative_path,
        *,
        project_doc=None,
        folder_name=None,
        parent_bucket=None,
    ):
        return self._resolve_project_relative_file(
            project_code,
            relative_path,
            allowed_suffixes={'.txt'},
            project_doc=project_doc,
            folder_name=folder_name,
            parent_bucket=parent_bucket,
        )

    def _resolve_project_image_path(
        self,
        project_code,
        relative_path,
        *,
        project_doc=None,
        folder_name=None,
        parent_bucket=None,
    ):
        return self._resolve_project_relative_file(
            project_code,
            relative_path,
            allowed_suffixes=self._NAS_IMAGE_SUFFIXES,
            project_doc=project_doc,
            folder_name=folder_name,
            parent_bucket=parent_bucket,
        )

    def _list_project_txt_files_sync(
        self,
        project_code,
        *,
        project_doc=None,
        folder_name=None,
        parent_bucket=None,
    ):
        folder = self._folder_for_project(
            project_code,
            project_doc,
            folder_name=folder_name,
            parent_bucket=parent_bucket,
        )
        if not folder:
            return []
        out = []
        for f in _iter_project_remark_txt(folder):
            try:
                st = f.stat()
                out.append({
                    'name': f.name,
                    'size': st.st_size,
                    'modified': datetime.utcfromtimestamp(st.st_mtime).isoformat(),
                    'relativePath': str(f.relative_to(folder)),
                })
            except OSError:
                continue
        return out

    def list_project_txt_files(self, project_code, *, project_doc=None, folder_name=None, parent_bucket=None):
        doc = project_doc
        fn = folder_name
        pb = parent_bucket
        result = _run_with_timeout(
            lambda: self._list_project_txt_files_sync(
                project_code,
                project_doc=doc,
                folder_name=fn,
                parent_bucket=pb,
            ),
            self._io_timeout(),
            default=None,
        )
        if result is None:
            logger.warning('[NAS] list_project_txt_files timed out for %s', project_code)
            return []
        return result

    def read_project_txt_file(
        self,
        project_code,
        relative_path,
        *,
        project_doc=None,
        folder_name=None,
        parent_bucket=None,
    ):
        doc = project_doc
        fn = folder_name
        pb = parent_bucket

        def _read():
            _root, target = self._resolve_project_txt_path(
                project_code,
                relative_path,
                project_doc=doc,
                folder_name=fn,
                parent_bucket=pb,
            )
            if target is None:
                return {'ok': False, 'error': 'Invalid path'}
            if not target.is_file():
                return {'ok': False, 'error': 'File not found', 'missing': True}
            try:
                content = target.read_text(encoding='utf-8')
                st = target.stat()
                return {
                    'ok': True,
                    'content': content,
                    'relativePath': relative_path,
                    'modified': datetime.utcfromtimestamp(st.st_mtime).isoformat(),
                }
            except OSError as e:
                return {'ok': False, 'error': str(e)}

        result = _run_with_timeout(_read, self._io_timeout(), default=None)
        if result is None:
            return {'ok': False, 'error': 'NAS read timed out'}
        return result

    def write_project_txt_file(
        self,
        project_code,
        relative_path,
        content,
        *,
        project_doc=None,
        folder_name=None,
        parent_bucket=None,
    ):
        doc = project_doc
        fn = folder_name
        pb = parent_bucket

        def _write():
            _root, target = self._resolve_project_txt_path(
                project_code,
                relative_path,
                project_doc=doc,
                folder_name=fn,
                parent_bucket=pb,
            )
            if target is None:
                return {'ok': False, 'error': 'Invalid path'}
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                text = content if content is not None else ''
                target.write_text(text, encoding='utf-8')
                st = target.stat()
                return {
                    'ok': True,
                    'relativePath': relative_path,
                    'modified': datetime.utcfromtimestamp(st.st_mtime).isoformat(),
                }
            except OSError as e:
                return {'ok': False, 'error': str(e)}

        result = _run_with_timeout(_write, self._io_timeout(), default=None)
        if result is None:
            return {'ok': False, 'error': 'NAS write timed out'}
        return result

    def _list_folder_files_sync(
        self,
        project_code,
        *,
        project_doc=None,
        folder_name=None,
        parent_bucket=None,
    ):
        folder = self._folder_for_project(
            project_code,
            project_doc,
            folder_name=folder_name,
            parent_bucket=parent_bucket,
        )
        if not folder:
            return []

        files = []
        seen = set()

        def _append_file(f: Path) -> None:
            key = str(f.resolve())
            if key in seen:
                return
            seen.add(key)
            st = f.stat()
            files.append({
                'name': f.name,
                'size': st.st_size,
                'modified': datetime.utcfromtimestamp(st.st_mtime).isoformat(),
                'relativePath': str(f.relative_to(folder)),
                'absolutePath': str(f),
            })

        for f in _iter_project_remark_txt(folder):
            try:
                _append_file(f)
            except OSError:
                continue
        for f in sorted(_iter_project_images(folder), key=lambda p: str(p)):
            try:
                _append_file(f)
            except OSError:
                continue
        return files

    def list_folder_files(self, project_code, *, project_doc=None, folder_name=None, parent_bucket=None):
        """List image files under the project folder (all subfolders, time-boxed)."""
        doc = project_doc
        fn = folder_name
        pb = parent_bucket
        result = _run_with_timeout(
            lambda: self._list_folder_files_sync(
                project_code,
                project_doc=doc,
                folder_name=fn,
                parent_bucket=pb,
            ),
            self._io_timeout(),
            default=None,
        )
        if result is None:
            logger.warning('[NAS] list_folder_files timed out for %s', project_code)
            return []
        return result


nas_mount = NasMountService()
