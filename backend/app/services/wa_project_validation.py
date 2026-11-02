"""WA project code/name uniqueness — scoped by NAS parent bucket when set."""
import re

from bson import ObjectId

from app import mongo


def normalize_code(code):
    return (code or '').upper().strip()


def normalize_name(name):
    return ' '.join((name or '').strip().split())


def _non_archived_filter():
    return {'status': {'$ne': 'archived'}}


def _parent_bucket_key(parent_bucket: str | None) -> str:
    if not parent_bucket:
        return ''
    from app.services.nas_bucket_code import nas_path_from_web_bucket

    return nas_path_from_web_bucket(parent_bucket).upper().strip()


def _project_parent_key(doc) -> str:
    return _parent_bucket_key((doc or {}).get('nasParentBucket'))


def _code_regex_query(code: str) -> dict:
    return {'code': {'$regex': f'^{re.escape(code)}$', '$options': 'i'}}


def find_project_by_code(code, *, parent_bucket=None, exclude_id=None):
    code = normalize_code(code)
    if not code:
        return None
    query = {**_non_archived_filter(), **_code_regex_query(code)}
    if exclude_id is not None:
        query['_id'] = {'$ne': ObjectId(exclude_id)}
    candidates = list(mongo.db.wa_projects.find(query))
    if parent_bucket is not None:
        pk = _parent_bucket_key(parent_bucket)
        for doc in candidates:
            if _project_parent_key(doc) == pk:
                return doc
        return None
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return None
    return None


def find_project_by_name(name, *, parent_bucket=None, exclude_id=None):
    name = normalize_name(name)
    if not name:
        return None
    name_key = name.casefold()
    query = {
        **_non_archived_filter(),
        '$or': [
            {'nameNormalized': name_key},
            {'name': {'$regex': f'^{re.escape(name)}$', '$options': 'i'}},
        ],
    }
    if exclude_id is not None:
        query['_id'] = {'$ne': ObjectId(exclude_id)}
    candidates = list(mongo.db.wa_projects.find(query))
    if parent_bucket is not None:
        pk = _parent_bucket_key(parent_bucket)
        for doc in candidates:
            if _project_parent_key(doc) == pk:
                return doc
        return None
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return None
    return None


def assert_code_available(code, *, parent_bucket=None, exclude_id=None):
    existing = find_project_by_code(
        code,
        parent_bucket=parent_bucket,
        exclude_id=exclude_id,
    )
    if existing:
        bucket = _parent_bucket_key(parent_bucket) or 'app-wide'
        return (
            f'Project code {normalize_code(code)} already exists under bucket {bucket}'
        )
    return None


def assert_name_available(name, *, parent_bucket=None, exclude_id=None):
    existing = find_project_by_name(
        name,
        parent_bucket=parent_bucket,
        exclude_id=exclude_id,
    )
    if existing:
        bucket = _parent_bucket_key(parent_bucket) or 'app-wide'
        return f'Project name "{normalize_name(name)}" already exists under bucket {bucket}'
    return None
