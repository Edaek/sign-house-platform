"""Match WA projects by site numbers and PJ-LO-HI folder ranges."""
import re

from app import mongo

# Folder codes like PJ-3000-3999 (NAS range buckets)
RANGE_FOLDER_RE = re.compile(r'^PJ-(\d+)-(\d+)$', re.I)
PJ_NUM_RE = re.compile(r'^[Pp][Jj][-]?(\d{1,6})$')


def is_range_folder_code(code):
    return bool(RANGE_FOLDER_RE.match((code or '').strip()))


def parse_pj_range(code):
    m = RANGE_FOLDER_RE.match((code or '').strip())
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


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
    """Projects whose PJ-LO-HI range contains *num_str*, or exact numeric code."""
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
