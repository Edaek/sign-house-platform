"""Parse WhatsApp messages to extract project code and keywords."""
import re
import logging
from app import mongo

logger = logging.getLogger(__name__)

PROJECT_PATTERNS = [
    re.compile(r'^[Pp][#\-]?(\d{1,4})\b'),
    re.compile(r'^#(\d{1,4})\b'),
]

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
    return commands.get(lower)
