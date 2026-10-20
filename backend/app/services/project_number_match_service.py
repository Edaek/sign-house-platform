"""Match WA projects by site numbers and PJ-LO-HI folder ranges."""
import re
from pathlib import Path

from app import mongo

# Folder codes like PJ-3000-3999 (NAS range buckets)
RANGE_FOLDER_RE = re.compile(r'^PJ-(\d+)-(\d+)$', re.I)
PJ_NUM_RE = re.compile(r'^[Pp][Jj][-]?(\d{1,6})$')
SITE_FOLDER_CODE_RE = re.compile(r'^PJ-(\d{1,6})(?:$|\s|_.*)', re.I)
PROJECT_CODE_RE = re.compile(r'^PJ-(\d{1,6})$', re.I)
STANDALONE_BUCKET_RE = re.compile(r'^T-\d+-\d+$', re.I)
NUMERIC_SITE_FOLDER_RE = re.compile(r'^\d{3,6}$')


def is_range_folder_code(code):
    return bool(RANGE_FOLDER_RE.match((code or '').strip()))


def is_nas_bucket_folder_code(code):
    """Top-level NAS bucket (PJ-lo-hi or T-lo-hi), not a site project."""
    c = (code or '').strip()
    return is_range_folder_code(c) or bool(STANDALONE_BUCKET_RE.match(c))


def parse_pj_range(code):
    m = RANGE_FOLDER_RE.match((code or '').strip())
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def is_nas_bucket_dir_name(dir_name):
    """Top-level or nested bucket folders (not assignable site projects)."""
    name = (dir_name or '').strip()
    if not name:
        return False
    if is_range_folder_code(name):
        return True
    if STANDALONE_BUCKET_RE.match(name):
        return True
    return False


def parse_site_folder_code(dir_name):
    """NAS directory name → canonical PJ-xxxx (excludes range buckets)."""
    name = (dir_name or '').strip()
    if not name or is_nas_bucket_dir_name(name):
        return None
    m = SITE_FOLDER_CODE_RE.match(name)
    if not m:
        return None
    return f'PJ-{m.group(1)}'.upper()


def parse_nas_site_folder_code(dir_name):
    """NAS folder name → wa_projects.code (PJ-xxxx, 1002, etc.)."""
    name = (dir_name or '').strip()
    if not name or is_nas_bucket_dir_name(name):
        return None
    pj = parse_site_folder_code(name)
    if pj:
        return pj
    if NUMERIC_SITE_FOLDER_RE.match(name):
        return name
    return None


def pj_number_from_project_code(code):
    m = PROJECT_CODE_RE.match((code or '').strip())
    if not m:
        return None
    return int(m.group(1))


def find_range_bucket_dir(watch_root, pj_number):
    """Return Path to PJ-lo-hi bucket on NAS mount containing *pj_number*, if any."""
    root = Path(watch_root) if watch_root else None
    if root is None or not root.is_dir() or pj_number is None:
        return None
    try:
        entries = root.iterdir()
    except OSError:
        return None
    for entry in entries:
        if not entry.is_dir() or entry.name.startswith('.'):
            continue
        bounds = parse_pj_range(entry.name)
        if bounds and bounds[0] <= pj_number <= bounds[1]:
            return entry
    return None


def primary_site_number(text):
    """Best-effort site number from classify input (3026, PJ3026, PJ-3026)."""
    trimmed = ' '.join((text or '').strip().split())
    if not trimmed:
        return None
    m = PJ_NUM_RE.match(trimmed)
    if m:
        return m.group(1)
    if trimmed.isdigit():
        return trimmed
    digits = re.findall(r'\d{3,6}', trimmed)
    if digits:
        return max(digits, key=len)
    return None


def _active_query(active_only=True):
    if active_only:
        return {'status': 'active'}
    return {'status': {'$ne': 'archived'}}


def match_projects_by_site_number(num_str, *, active_only=True):
    """Legacy: PJ-LO-HI range containment (NAS helpers only — not WA classify)."""
    if not num_str or not str(num_str).isdigit():
        return []
    try:
        n = int(num_str)
    except ValueError:
        return []

    query = _active_query(active_only)
    projects = list(mongo.db.wa_projects.find(query))
    hits = []
    for proj in projects:
        code = (proj.get('code') or '').strip()
        bounds = parse_pj_range(code)
        if bounds and bounds[0] <= n <= bounds[1]:
            hits.append((proj, 100, 'range'))
            continue
        if code.isdigit() and int(code) == n:
            hits.append((proj, 100, 'exact_num'))
    return hits


def is_wa_classify_target(proj):
    """Site/subfolder projects eligible for WhatsApp assign — not range or bucket containers."""
    if not proj:
        return False
    code = (proj.get('code') or '').strip()
    if not code:
        return False
    if is_range_folder_code(code):
        return False
    if STANDALONE_BUCKET_RE.match(code) and not (proj.get('nasParentBucket') or '').strip():
        return False
    return True


def list_wa_classify_target_projects(*, active_only=True, limit=None):
    query = _active_query(active_only)
    projects = list(mongo.db.wa_projects.find(query).sort([('nasParentBucket', 1), ('code', 1)]))
    out = [p for p in projects if is_wa_classify_target(p)]
    if limit is not None:
        return out[:limit]
    return out


def match_site_projects_by_number(num_str, *, active_only=True):
    """Match NAS site projects by site number (PJ-n or numeric folder code e.g. 1002)."""
    if not num_str or not str(num_str).isdigit():
        return []
    try:
        n = int(num_str)
    except ValueError:
        return []

    query = _active_query(active_only)
    canonical = f'PJ-{n}'
    proj = mongo.db.wa_projects.find_one({
        **query,
        'code': {'$regex': f'^{re.escape(canonical)}$', '$options': 'i'},
    })
    if proj and is_wa_classify_target(proj):
        return [(proj, 100, 'site_code')]

    for code in (str(n), str(num_str).strip()):
        proj = mongo.db.wa_projects.find_one({
            **query,
            'code': {'$regex': f'^{re.escape(code)}$', '$options': 'i'},
        })
        if proj and is_wa_classify_target(proj):
            return [(proj, 100, 'exact_num')]
    return []
