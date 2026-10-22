"""Match WA projects by site numbers and PJ-LO-HI folder ranges."""
import re
from pathlib import Path

_WA_LABEL_MAX = 120

from app import mongo

# Folder codes like PJ-3000-3999 (NAS range buckets)
RANGE_FOLDER_RE = re.compile(r'^PJ-(\d+)-(\d+)$', re.I)
# Any prefix + lo-hi by numeric range (T-1000-2000, S-1000-2000, …) — not site PJ-3026.
GENERIC_RANGE_BUCKET_RE = re.compile(r'^(.+)-(\d+)-(\d+)$', re.I)
PJ_NUM_RE = re.compile(r'^[Pp][Jj][-]?(\d{1,6})$')
SITE_FOLDER_CODE_RE = re.compile(r'^PJ-(\d{1,6})(?:$|\s|_.*)', re.I)
PROJECT_CODE_RE = re.compile(r'^PJ-(\d{1,6})$', re.I)
NUMERIC_SITE_FOLDER_RE = re.compile(r'^\d{3,6}$')


def is_range_folder_code(code):
    return bool(RANGE_FOLDER_RE.match((code or '').strip()))


def parse_range_bucket(code):
    """Parse NAS range bucket folder → (lo, hi) site numbers; None if not a range bucket."""
    c = (code or '').strip()
    if not c:
        return None
    m = RANGE_FOLDER_RE.match(c)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
    else:
        m = GENERIC_RANGE_BUCKET_RE.match(c)
        if not m:
            return None
        lo, hi = int(m.group(2)), int(m.group(3))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def parse_pj_range(code):
    return parse_range_bucket(code) if is_range_folder_code(code) else None


def parse_t_range(code):
    return parse_range_bucket(code)


def is_nas_bucket_folder_code(code):
    """NAS folder whose code is a numeric lo-hi range (any prefix), not a single site."""
    return parse_range_bucket(code) is not None


# Backward-compatible alias (nas_sync imports)
STANDALONE_BUCKET_RE = GENERIC_RANGE_BUCKET_RE


def bucket_range_bounds(bucket_code):
    return parse_range_bucket(bucket_code)


def bucket_contains_site_number(bucket_code, site_n: int) -> bool:
    bounds = bucket_range_bounds(bucket_code)
    if not bounds:
        return False
    return bounds[0] <= site_n <= bounds[1]


def find_buckets_containing_site_number(site_n, *, active_only=True):
    """Range buckets (by lo-hi site numbers) that contain this site number."""
    try:
        n = int(site_n)
    except (TypeError, ValueError):
        return []

    query = _active_query(active_only)
    codes = set()
    for proj in mongo.db.wa_projects.find(query, {'code': 1, 'nasParentBucket': 1}):
        code = (proj.get('code') or '').strip()
        if code and is_nas_bucket_folder_code(code) and bucket_contains_site_number(code, n):
            codes.add(code)
        parent = (proj.get('nasParentBucket') or '').strip()
        if parent and is_nas_bucket_dir_name(parent) and bucket_contains_site_number(parent, n):
            codes.add(parent)
    return sorted(codes, key=lambda c: c.upper())


def _site_number_from_project(proj):
    code = (proj.get('code') or '').strip()
    if code.isdigit():
        return int(code)
    pj_n = pj_number_from_project_code(code)
    return pj_n


def match_classify_sites_near_number_in_buckets(num_str, bucket_codes, *, active_only=True):
    """All site projects in range buckets, ranked by nearness to the typed number."""
    sn = str(num_str).strip()
    if not sn.isdigit() or not bucket_codes:
        return []
    try:
        n = int(sn)
    except ValueError:
        return []

    bucket_set = {b.upper() for b in bucket_codes if (b or '').strip()}
    query = _active_query(active_only)
    hits = []
    seen = set()
    for proj in mongo.db.wa_projects.find(query):
        if not is_wa_classify_target(proj):
            continue
        pid = str(proj.get('_id', ''))
        parent = (proj.get('nasParentBucket') or '').strip()
        if not parent or parent.upper() not in bucket_set:
            continue
        site_num = _site_number_from_project(proj)
        if site_num is None or pid in seen:
            continue
        dist = abs(site_num - n)
        score = 100 if site_num == n else max(50, 99 - dist)
        seen.add(pid)
        hits.append((proj, score))
    hits.sort(key=lambda t: (-t[1], abs(_site_number_from_project(t[0]) - n)))
    return hits


def is_nas_bucket_dir_name(dir_name):
    """Top-level or nested bucket folders (not assignable site projects)."""
    return parse_range_bucket(dir_name) is not None


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
    if parse_range_bucket(code) is not None and not (proj.get('nasParentBucket') or '').strip():
        return False
    return True


def _normalize_classify_label(text):
    return ' '.join((text or '').strip().split()).upper()


def classify_input_matches_full_display(label, project) -> bool:
    """True only when input equals the full NAS folder label shown in WhatsApp lists."""
    if not project or not (label or '').strip():
        return False
    lab = ' '.join((label or '').strip().split())
    if lab.isdigit():
        return False
    if re.fullmatch(r'[Pp][Jj][-]?\d{1,6}', lab):
        display_probe = wa_classify_display_label(project, max_len=0)
        if display_probe and (' ' in display_probe or '_' in display_probe):
            return False
    display = wa_classify_display_label(project, max_len=0)
    if not display:
        return False
    return _normalize_classify_label(lab) == _normalize_classify_label(display)


def wa_classify_display_label(proj, *, max_len=_WA_LABEL_MAX):
    """WhatsApp / list label — prefer nasFolderName (longest NAS folder name)."""
    if not proj:
        return ''
    from app.services.nas_sync_service import enrich_wa_project_display

    enrich_wa_project_display(proj)
    code = (proj.get('code') or '').strip()
    label = (proj.get('nasFolderName') or '').strip() or code
    if max_len and len(label) > max_len:
        return label[: max_len - 1].rstrip() + '…'
    return label


def list_wa_classify_target_projects(*, active_only=True, limit=None):
    query = _active_query(active_only)
    projects = list(mongo.db.wa_projects.find(query).sort([('nasParentBucket', 1), ('code', 1)]))
    out = [p for p in projects if is_wa_classify_target(p)]
    if limit is not None:
        return out[:limit]
    return out


def match_classify_targets_by_site_number(num_str, *, active_only=True):
    """Strict site-number match for WA classify (1007 matches PJ-1007/1007, not PJ-3007)."""
    if not num_str or not str(num_str).isdigit():
        return []
    try:
        n = int(num_str)
    except ValueError:
        return []

    query = _active_query(active_only)
    canonical = f'PJ-{n}'
    hits = []
    seen = set()
    for proj in mongo.db.wa_projects.find(query):
        if not is_wa_classify_target(proj):
            continue
        pid = str(proj.get('_id', ''))
        code = (proj.get('code') or '').strip()
        score = None
        if code.isdigit() and int(code) == n:
            score = 100
        elif code.upper() == canonical.upper():
            score = 99
        else:
            pj_n = pj_number_from_project_code(code)
            if pj_n is not None and pj_n == n:
                score = 98
        if score is None or pid in seen:
            continue
        seen.add(pid)
        hits.append((proj, score))
    hits.sort(key=lambda t: t[1], reverse=True)
    return hits


def _digit_mismatch_count(sn, pn):
    if len(sn) != len(pn):
        return max(len(sn), len(pn))
    return sum(a != b for a, b in zip(sn, pn))


def _typo_site_number_pair(sn, pn):
    from rapidfuzz.distance import Levenshtein

    if not sn or not pn:
        return None
    dist = Levenshtein.distance(sn, pn)
    if dist <= 0:
        return None
    try:
        sn_i, pn_i = int(sn), int(pn)
    except ValueError:
        return None
    # Same last two digits (1007 vs 2807/3007) — partial match, not a useful typo hint.
    if len(sn) >= 4 and len(pn) >= 4 and sn[-2:] == pn[-2:]:
        return None
    mismatch = _digit_mismatch_count(sn, pn)
    return dist, sn_i, pn_i, mismatch


def match_classify_typo_site_numbers(num_str, *, active_only=True, max_distance=2):
    """Site-number edit-distance typos (generic — no bucket-specific presets)."""
    sn = str(num_str).strip()
    if not sn.isdigit() or len(sn) < 3:
        return []

    query = _active_query(active_only)
    hits = []
    seen = set()
    for proj in mongo.db.wa_projects.find(query):
        if not is_wa_classify_target(proj):
            continue
        pid = str(proj.get('_id', ''))
        code = (proj.get('code') or '').strip()
        pn = code if code.isdigit() else None
        if pn is None:
            pj_n = pj_number_from_project_code(code)
            pn = str(pj_n) if pj_n is not None else None
        if not pn or pid in seen:
            continue
        pair = _typo_site_number_pair(sn, pn)
        if pair is None:
            continue
        dist, sn_i, pn_i, mismatch = pair
        if dist > max_distance:
            continue
        seen.add(pid)
        score = 90 - dist * 5
        hits.append((proj, score, dist, mismatch, abs(pn_i - sn_i)))
    hits.sort(key=lambda t: (-t[1], t[2], -t[3], t[4], (t[0].get('code') or '')))
    return [(p, s) for p, s, *_rest in hits]


def match_classify_cross_bucket_typo_suggestions(
    num_str,
    home_bucket_codes,
    *,
    active_only=True,
    max_distance=2,
    limit=1,
):
    """Typo matches outside range bucket(s) that already contain the typed site number."""
    if not home_bucket_codes or limit <= 0:
        return []
    home_set = {b.upper() for b in home_bucket_codes if (b or '').strip()}
    typos = match_classify_typo_site_numbers(
        num_str, active_only=active_only, max_distance=max_distance,
    )
    cross = []
    for proj, score in typos:
        parent = (proj.get('nasParentBucket') or '').strip().upper()
        if parent and parent in home_set:
            continue
        cross.append((proj, score))
    return cross[:limit]


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
