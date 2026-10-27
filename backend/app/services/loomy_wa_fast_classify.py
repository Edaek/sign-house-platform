"""Deterministic classify on pool intake — Loomy mode, no legacy receipt bot."""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from app.services.loomy_wa_mongo_site_classify import try_loomy_mongo_site_classify_reply

logger = logging.getLogger(__name__)


def _fast_classify_nas_enabled() -> bool:
    return os.environ.get('LOOMY_WA_FAST_CLASSIFY_NAS', '').lower() in ('1', 'true', 'yes')


def try_loomy_fast_classify_reply(
    *,
    phone: str,
    caption: str,
    pool_ids: List[str],
    group_id: Optional[str] = None,
) -> Optional[str]:
    """
    Heuristic + project DB resolve (same as legacy auto bot brain, Loomy phrasing).
    Returns WhatsApp reply text if handled; None → defer to MCP agent.
    """
    from app.services.wa_classify_mode import wa_loomy_agent_enabled

    if not wa_loomy_agent_enabled():
        return None
    cap = (caption or '').strip()
    if not cap or not pool_ids:
        return None

    from app.services.message_parser_service import split_classify_label_and_remark
    from app.services.project_ai_resolve_service import (
        coerce_assign_to_confirm,
        resolve_classify_input,
    )

    trimmed = ' '.join(cap.split())
    label, remark = split_classify_label_and_remark(trimmed)
    match_key = label or trimmed

    mongo_site = try_loomy_mongo_site_classify_reply(
        phone=phone,
        caption=cap,
        pool_ids=pool_ids,
        group_id=group_id,
    )
    if mongo_site:
        return mongo_site

    from app.services.image_pool_service import MatchResult, assign_images_to_project, match_project_ext
    from app.services.project_number_match_service import (
        is_wa_classify_target,
        loomy_caption_site_matches_project,
        wa_classify_display_label_mongo_only,
        loomy_primary_site_number,
        match_classify_targets_by_site_number,
    )
    from app.services.nas_watcher_service import nas_mount

    site = loomy_primary_site_number(trimmed)

    ext = match_project_ext(trimmed, active_only=True) if not site else MatchResult()
    if site and not ext.project and not ext.candidates:
        targets = match_classify_targets_by_site_number(site, active_only=True)
        if len(targets) == 1:
            ext = MatchResult(project=targets[0][0], remark=remark or ext.remark)
        elif len(targets) > 1:
            ext = MatchResult(candidates=targets, remark=remark or ext.remark)

    if ext.project and is_wa_classify_target(ext.project):
        if loomy_caption_site_matches_project(trimmed, ext.project):
            n = assign_images_to_project(
                pool_ids,
                ext.project,
                'loomy',
                remark=ext.remark or remark,
                group_id=group_id,
            )
            if n > 0:
                return _assign_msg(ext.project, n)

    if ext.candidates:
        from app.services.loomy_wa_pick_store import store_loomy_wa_pick_options
        from app.services.project_ai_resolve_service import _build_classify_list_message

        list_label = str(site or match_key)
        store_loomy_wa_pick_options(
            phone=phone,
            group_id=group_id,
            candidates=ext.candidates,
            pool_ids=pool_ids,
        )
        return _build_classify_list_message(list_label, ext.candidates)

    if not _fast_classify_nas_enabled():
        return None

    if not nas_mount.probe_responsive(timeout_s=2):
        return None

    try:
        resolve = coerce_assign_to_confirm(
            resolve_classify_input(cap, active_only=True),
            match_key,
        )
    except Exception:
        logger.exception('[LoomyWA] fast classify failed (NAS/DB); defer to agent')
        return None

    if resolve.action == 'assign' and resolve.project:
        n = assign_images_to_project(
            pool_ids,
            resolve.project,
            'loomy',
            remark=resolve.remark,
            group_id=group_id,
        )
        if n <= 0:
            return None
        return _assign_msg(resolve.project, n)

    msg = (resolve.user_message or '').strip()
    if msg and resolve.action in ('list', 'suggest'):
        return msg

    return None


def _assign_msg(project, n: int) -> str:
    from app.services.loomy_wa_mongo_site_classify import _assign_success_message

    return _assign_success_message(project, n)
