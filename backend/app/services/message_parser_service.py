"""Parse WhatsApp messages to extract project code and keywords."""
import re
import logging
from app import mongo

logger = logging.getLogger(__name__)

PROJECT_PATTERNS = [
    re.compile(r'^[Pp][#\-]?(\d{1,4})\b'),
    re.compile(r'^#(\d{1,4})\b'),
]

# Leading project number + free-text remark, e.g. "2899 carpark sign"
LEADING_PROJECT_NUM_RE = re.compile(r'^(\d{1,6})(?:\s+(.*))?$', re.DOTALL)


def split_classify_label_and_remark(text):
    """Split user classify line into project label and trailing remark.

    Examples:
        "2899 carpark sign" -> ("2899", "carpark sign")
        "P-001 lobby"       -> ("1", "lobby")  # numeric part for code expansion
        "Sunrise Tower"     -> ("Sunrise Tower", "")
    """
    trimmed = ' '.join((text or '').strip().split())
    if not trimmed:
        return '', ''

    for pattern in PROJECT_PATTERNS:
        m = pattern.match(trimmed)
        if m:
            return m.group(1), trimmed[m.end():].strip()

    m = LEADING_PROJECT_NUM_RE.match(trimmed)
    if m and m.group(2) is not None and str(m.group(2)).strip():
        return m.group(1), str(m.group(2)).strip()

    parts = trimmed.split(None, 1)
    if len(parts) == 2:
        first, rest = parts[0].strip(), parts[1].strip()
        if rest and _first_token_is_classify_code(first):
            return first, rest

    return trimmed, ''


_EXPLICIT_NOTE_RE = re.compile(
    r'(?:备注|備註|remark)\s*(?:是|為|为|[:：])\s*(.+)$',
    re.I,
)


def site_note_from_text(text):
    """Site-log note for the NAS day txt.

    ``归类到1005备注是 这是一条备注信息`` → ``这是一条备注信息``
    ``1005 Test`` → ``Test``
    A bare project code → None.
    """
    raw = (text or '').strip()
    if not raw or raw.lower() == '[pool media]':
        return None
    collapsed = ' '.join(raw.split())
    matched = _EXPLICIT_NOTE_RE.search(collapsed)
    if matched and matched.group(1).strip():
        return matched.group(1).strip()
    extracted = trailing_classify_remark(collapsed)
    if extracted:
        return extracted
    return None


def trailing_classify_remark(text):
    """User-facing remark only — drop leading project code (e.g. ``3027 备注`` → ``备注``)."""
    trimmed = ' '.join((text or '').strip().split())
    if not trimmed:
        return None
    label, remark = split_classify_label_and_remark(trimmed)
    if remark:
        return remark
    if _first_token_is_classify_code(label) and trimmed == label:
        return None
    if _first_token_is_classify_code(label) and trimmed.startswith(label + ' '):
        return trimmed[len(label) :].strip() or None
    return None


def _first_token_is_classify_code(token):
    """First word is a project code token (not a multi-word project name)."""
    if not token:
        return False
    if token.isdigit():
        return True
    for pattern in PROJECT_PATTERNS:
        if pattern.match(token):
            return True
    # Uppercase codes like TEST (not "Sunrise" style names)
    if len(token) >= 2 and re.match(r'^[A-Z0-9#_-]+$', token):
        return True
    try:
        if mongo.db and mongo.db.wa_projects.find_one({
            'status': 'active',
            'code': {'$regex': f'^{re.escape(token)}$', '$options': 'i'},
        }):
            return True
    except Exception:
        pass
    return False


def extract_project_code(text):
    trimmed = text.strip()
    for pattern in PROJECT_PATTERNS:
        m = pattern.match(trimmed)
        if m:
            num = m.group(1).zfill(3)
            return f'P-{num}'
    project = mongo.db.wa_projects.find_one(
        {'code': re.compile(rf'^{re.escape(trimmed)}$', re.IGNORECASE), 'status': 'active'}
    )
    if project:
        return project['code']
    return None

def remove_project_code(text):
    _label, remark = split_classify_label_and_remark(text)
    if remark:
        return remark
    return re.sub(r'^[Pp]?[#\-]?\d{1,4}\s*', '', text).strip()

def parse_message(text):
    trimmed = text.strip()
    project_code = extract_project_code(trimmed)
    if not project_code:
        return {'success': False, 'errorType': 'missing_project_id', 'rawText': trimmed}
    
    remaining = remove_project_code(trimmed)
    remaining_lower = remaining.lower()
    
    # Load type keywords
    type_keywords = list(mongo.db.wa_keywords.find({'type': 'type_keyword', 'isActive': True}))
    
    matched_keyword = None
    for kw in type_keywords:
        all_terms = [kw['term']] + kw.get('synonyms', [])
        for term in all_terms:
            escaped = re.escape(term)
            regex = re.compile(rf'(?:^|\s){escaped}(?:\s|$)', re.IGNORECASE)
            if remaining_lower.startswith(term) or regex.search(remaining_lower):
                matched_keyword = kw['term']
                break
        if matched_keyword:
            break
    
    if not matched_keyword:
        words = remaining_lower.split()
        all_terms_flat = []
        for kw in type_keywords:
            all_terms_flat.extend([kw['term']] + kw.get('synonyms', []))
        suggestions = list(set(t for t in all_terms_flat if any(t in w or w in t for w in words)))[:3]
        return {
            'success': False,
            'errorType': 'unrecognized_keyword' if suggestions else 'missing_keyword',
            'suggestions': suggestions or None,
            'rawText': trimmed
        }
    
    # Tag keywords
    tag_keywords = list(mongo.db.wa_keywords.find({'type': 'tag_keyword', 'isActive': True}))
    matched_tags = []
    for tag in tag_keywords:
        all_terms = [tag['term']] + tag.get('synonyms', [])
        for term in all_terms:
            escaped = re.escape(term)
            regex = re.compile(rf'(?:^|\s){escaped}(?:\s|$)', re.IGNORECASE)
            if regex.search(remaining_lower):
                matched_tags.append(tag['term'])
                break
    
    # Description
    description = remaining
    idx = remaining_lower.find(matched_keyword)
    if idx >= 0:
        description = remaining[idx + len(matched_keyword):].strip()
    
    return {
        'success': True,
        'projectCode': project_code,
        'typeKeyword': matched_keyword,
        'tagKeywords': matched_tags,
        'description': description,
    }

def is_command(text):
    if not text:
        return None
    lower = re.sub(r'^[\/!]', '', text.strip().lower())
    lower = re.sub(r'[!?.,]$', '', lower)
    commands = {'help': 'help', 'keywords': 'keywords', 'projects': 'projects'}
    if lower.startswith('move'):
        return 'move'
    return commands.get(lower)
