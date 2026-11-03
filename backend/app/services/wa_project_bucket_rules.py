"""NAS bucket vs site project rules — align with frontend isBucketContainerSite."""
from __future__ import annotations

_RESERVED_NAS_FOLDER_NAMES = frozenset({
    'photo',
    'processed',
    'process',
    'tmp',
    'temp',
    '.ds_store',
})


def is_reserved_nas_folder_name(name: str | None) -> bool:
    """Structural NAS dirs under a site — not WA classify targets."""
    key = (name or '').strip().casefold()
    if not key:
        return False
    if key in _RESERVED_NAS_FOLDER_NAMES:
        return True
    if key.startswith('.'):
        return True
    return False


def _norm_code(code: str | None) -> str:
    return (code or '').strip().upper()


def is_bucket_container_project(proj) -> bool:
    """
    Root bucket container — not a site subfolder for pool assign / WA classify.
    Mirrors frontend isBucketContainerSite + standalone/range bucket rows.
    """
    if not proj:
        return False
    code = _norm_code(proj.get('code'))
    if not code:
        return False

    from app.services.project_number_match_service import (
        is_nas_bucket_folder_code,
        is_range_folder_code,
    )

    parent_raw = (proj.get('nasParentBucket') or '').strip()
    if parent_raw:
        from app.services.nas_bucket_code import nas_path_from_web_bucket

        parent = _norm_code(nas_path_from_web_bucket(parent_raw))
        if parent and code == parent:
            return True
        if is_range_folder_code(code) and code == parent:
            return True

    if not parent_raw:
        if is_range_folder_code(code) or is_nas_bucket_folder_code(code):
            return True
        from app.services.nas_sync_service import _is_nas_root_bucket_dir

        if _is_nas_root_bucket_dir(code):
            return True

    return False
