"""Coalesce WhatsApp assignment confirmations (multi-file bursts → one reply)."""
import logging
import os
import threading
from typing import Any, Dict, Optional

from app.services.wa_send_service import send_message, send_group_message

logger = logging.getLogger(__name__)

DEBOUNCE_S = float(os.environ.get('ASSIGN_CONFIRM_DEBOUNCE_S', '2.0'))

_lock = threading.Lock()
_timers: Dict[str, threading.Timer] = {}
_pending: Dict[str, Dict[str, Any]] = {}


def assignment_confirmation_text(project: dict, count: int) -> str:
    from bson import ObjectId

    from app import mongo
    from app.services.nas_sync_service import enrich_wa_projects_display
    from app.services.project_number_match_service import wa_classify_display_label

    pid = project.get('_id')
    if pid is not None:
        try:
            oid = pid if isinstance(pid, ObjectId) else ObjectId(str(pid))
            fresh = mongo.db.wa_projects.find_one({'_id': oid})
            if fresh:
                project = fresh
        except Exception:
            pass
    enrich_wa_projects_display([project])
    name = wa_classify_display_label(project, max_len=500)
    if count > 1:
        return f'✅ {count} 個檔案已歸類至專案：\n{name}'
    return f'✅ 檔案已歸類至專案：\n{name}'


def schedule_assignment_confirmation(
    project: dict,
    count: int,
    *,
    phone: Optional[str] = None,
    group_id: Optional[str] = None,
) -> None:
    """Merge confirmations for the same chat + project within DEBOUNCE_S."""
    if count <= 0 or not project:
        return

    proj_key = str(project.get('_id') or project.get('code', ''))
    if group_id:
        key = f'g:{group_id}:{proj_key}'
    elif phone:
        key = f'p:{phone}:{proj_key}'
    else:
        return

    with _lock:
        entry = _pending.get(key)
        if not entry:
            entry = {
                'count': 0,
                'project': project,
                'phone': phone,
                'group_id': group_id,
            }
            _pending[key] = entry
        entry['count'] += count

        existing = _timers.pop(key, None)
        if existing:
            existing.cancel()

        timer = threading.Timer(DEBOUNCE_S, _flush, args=(key,))
        timer.daemon = True
        timer.start()
        _timers[key] = timer


def _flush(key: str) -> None:
    with _lock:
        entry = _pending.pop(key, None)
        _timers.pop(key, None)
    if not entry or entry['count'] <= 0:
        return

    text = assignment_confirmation_text(entry['project'], entry['count'])
    try:
        import os
        from app import create_app

        app = create_app(os.environ.get('FLASK_CONFIG', 'development'))
        with app.app_context():
            if entry.get('group_id'):
                send_group_message(entry['group_id'], text)
            elif entry.get('phone'):
                send_message(entry['phone'], text)
    except Exception:
        logger.exception('[AssignNotify] Failed to send confirmation')
