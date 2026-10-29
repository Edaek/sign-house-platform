"""Map UI bucket keys (__standalone:LIGHT) to physical NAS folder names (LIGHT)."""

STANDALONE_PREFIX = '__standalone:'


def nas_path_from_web_bucket(bucket_code: str) -> str:
    """Physical directory name under NAS watch root."""
    b = (bucket_code or '').strip()
    if b.lower().startswith(STANDALONE_PREFIX):
        return b.split(':', 1)[1].strip()
    return b


def web_bucket_key_for_nas_root(nas_dir_name: str) -> str:
    """URL / UI bucket code for a top-level NAS directory."""
    from app.services.project_number_match_service import is_range_folder_code

    n = (nas_dir_name or '').strip()
    if not n:
        return n
    if is_range_folder_code(n):
        return n.upper()
    return f'{STANDALONE_PREFIX}{n.upper()}'


def nas_parent_bucket_match_values(bucket_code: str) -> tuple[str, ...]:
    """Mongo nasParentBucket values that refer to the same physical bucket."""
    path = nas_path_from_web_bucket(bucket_code)
    if not path:
        return ()
    variants = {path, f'{STANDALONE_PREFIX}{path.upper()}'}
    raw = (bucket_code or '').strip()
    if raw:
        variants.add(raw)
    return tuple(v for v in variants if v)


def bucket_lookup_keys(bucket_code: str) -> list[str]:
    """Lowercase keys for in-memory bucket-children cache (UI + NAS names)."""
    raw = (bucket_code or '').strip()
    path = nas_path_from_web_bucket(raw)
    keys: list[str] = []
    for candidate in (raw, path, f'{STANDALONE_PREFIX}{path.upper()}' if path else ''):
        k = (candidate or '').strip().lower()
        if k and k not in keys:
            keys.append(k)
    return keys
