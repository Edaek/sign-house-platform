"""Multi-turn WhatsApp↔Loom classify state (Sign House holds messages; Loom read-only MCP)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def _state_key(*, phone: str, group_id: Optional[str]) -> str:
    if group_id:
        return f'loomy_wa_pending:g:{group_id}:{phone}'
    return f'loomy_wa_pending:p:{phone}'


def get_pending_assignment(*, phone: str, group_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    from app import mongo

    if mongo.db is None:
        return None
    doc = mongo.db.wa_system.find_one({'_id': _state_key(phone=phone, group_id=group_id)})
    if not doc or not doc.get('poolImageIds'):
        return None
    return {
        'poolImageIds': list(doc.get('poolImageIds') or []),
        'askedAt': doc.get('askedAt'),
        'previousDecision': doc.get('previousDecision') or '',
    }


def set_pending_assignment(
    *,
    phone: str,
    group_id: Optional[str],
    pool_image_ids: List[str],
    previous_decision: str = '',
) -> None:
    from app import mongo

    if not pool_image_ids:
        return
    if mongo.db is None:
        return
    now = datetime.utcnow()
    mongo.db.wa_system.update_one(
        {'_id': _state_key(phone=phone, group_id=group_id)},
        {
            '$set': {
                'poolImageIds': list(pool_image_ids),
                'askedAt': now,
                'previousDecision': (previous_decision or '')[:2000],
                'updatedAt': now,
            },
        },
        upsert=True,
    )


def clear_pending_assignment(*, phone: str, group_id: Optional[str]) -> None:
    from app import mongo

    if mongo.db is None:
        return
    mongo.db.wa_system.delete_one({'_id': _state_key(phone=phone, group_id=group_id)})
