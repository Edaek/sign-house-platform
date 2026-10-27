"""WA project code/name uniqueness (each field only compared to itself)."""
import re

from bson import ObjectId

from app import mongo


def normalize_code(code):
    return (code or '').upper().strip()


def normalize_name(name):
    return ' '.join((name or '').strip().split())


def _non_archived_filter():
    return {'status': {'$ne': 'archived'}}


def find_project_by_code(code, *, exclude_id=None):
    code = normalize_code(code)
    if not code:
        return None
    query = {
        **_non_archived_filter(),
        'code': {'$regex': f'^{re.escape(code)}$', '$options': 'i'},
    }
    if exclude_id is not None:
        query['_id'] = {'$ne': ObjectId(exclude_id)}
    return mongo.db.wa_projects.find_one(query)


def find_project_by_name(name, *, exclude_id=None):
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
    return mongo.db.wa_projects.find_one(query)


def assert_code_available(code, *, exclude_id=None):
    existing = find_project_by_code(code, exclude_id=exclude_id)
    if existing:
        return f'Project code {normalize_code(code)} already exists'
    return None


def assert_name_available(name, *, exclude_id=None):
    existing = find_project_by_name(name, exclude_id=exclude_id)
    if existing:
        return f'Project name "{normalize_name(name)}" already exists'
    return None
