"""Assignment confirmation copy for MCP/API — WhatsApp send is Loom-only."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def assignment_confirmation_text(project: dict, count: int) -> str:
    """Text shape for tools/Loom; not sent locally over Wakka."""
    from bson import ObjectId

    from app import mongo
    from app.services.nas_sync_service import enrich_wa_projects_display
    from app.services.project_number_match_service import wa_classify_display_label

    proj = dict(project)
    chosen_folder = (proj.get('nasFolderName') or '').strip()
    if not chosen_folder:
        pid = proj.get('_id')
        if pid is not None:
            try:
                oid = pid if isinstance(pid, ObjectId) else ObjectId(str(pid))
                fresh = mongo.db.wa_projects.find_one({'_id': oid})
                if fresh:
                    proj = dict(fresh)
            except Exception:
                pass
        enrich_wa_projects_display([proj])
        name = wa_classify_display_label(proj, max_len=500)
    else:
        name = chosen_folder
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
    """No-op: Loom confirms assign in WhatsApp via MCP + Persona."""
    del project, count, phone, group_id
    logger.debug('[AssignNotify] Skipped local WA (Loom owns messaging)')
