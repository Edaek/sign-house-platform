"""WA project code uniqueness."""
import re

from bson import ObjectId

from app import mongo


def normalize_code(code):
    return (code or '').upper().strip()


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


def assert_code_available(code, *, exclude_id=None):
    existing = find_project_by_code(code, exclude_id=exclude_id)
    if existing:
        return f'Project code {normalize_code(code)} already exists'
    return None
