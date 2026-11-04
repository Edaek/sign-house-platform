"""Mongo-only site-number pool classify — no NAS list_folders / Ollama."""
from __future__ import annotations

from typing import List, Optional


def _assign_success_message(project, count: int, *, pool_ids=None) -> str:
    from app import mongo
    from app.services.nas_site_remark_service import assign_photo_day_hk
    from app.services.project_number_match_service import wa_classify_display_label_mongo_only
    from bson import ObjectId

    label_txt = wa_classify_display_label_mongo_only(project, max_len=500)
    day = assign_photo_day_hk([])
    if pool_ids:
        oids = []
        for pid in pool_ids:
            try:
                oids.append(ObjectId(pid))
            except Exception:
                continue
        if oids:
            imgs = list(mongo.db.pool_images.find({'_id': {'$in': oids}}))
            day = assign_photo_day_hk(imgs)
    return (
        f'✅ 已歸類 {count} 張照片至：\n{label_txt}\n'
        f'📁 共享盤：Photo/{day}/（不是 PJ-xxxxA 短名資料夾根目錄）'
    )


def try_loomy_mongo_site_classify_reply(
    *,
    phone: str,
    caption: str,
    pool_ids: List[str],
    group_id: Optional[str] = None,
) -> Optional[str]:
    """
    Match leading site number (e.g. 1006) against Mongo wa_projects only.
    Returns WhatsApp reply if handled; None → caller may try other classify paths.
    """
    from app.services.image_pool_service import assign_images_to_project
    from app.services.project_number_match_service import (
        is_wa_classify_target,
        loomy_caption_site_matches_project,
        loomy_primary_site_number,
        match_classify_targets_by_site_number,
    )

    trimmed = ' '.join((caption or '').strip().split())
    if not trimmed or not pool_ids:
        return None

    site = loomy_primary_site_number(trimmed)
    if not site:
        return None

    targets = match_classify_targets_by_site_number(site, active_only=True)
    if len(targets) == 1:
        proj = targets[0][0]
        if is_wa_classify_target(proj) and loomy_caption_site_matches_project(trimmed, proj):
            from app.services.message_parser_service import split_classify_label_and_remark

            _, remark = split_classify_label_and_remark(trimmed)
            n = assign_images_to_project(
                pool_ids,
                proj,
                'loomy',
                remark=remark,
                group_id=group_id,
            )
            if n > 0:
                return _assign_success_message(proj, n, pool_ids=pool_ids)
        return None

    if len(targets) > 1:
        from app.services.loomy_wa_pick_store import store_loomy_wa_pick_options
        from app.services.project_ai_resolve_service import _build_classify_list_message

        store_loomy_wa_pick_options(
            phone=phone,
            group_id=group_id,
            candidates=targets,
            pool_ids=pool_ids,
        )
        return _build_classify_list_message(site, targets)

    from app.services.image_pool_service import match_project_ext

    ext = match_project_ext(trimmed, active_only=True)
    if ext.project and is_wa_classify_target(ext.project):
        from app.services.message_parser_service import split_classify_label_and_remark

        _, remark = split_classify_label_and_remark(trimmed)
        n = assign_images_to_project(
            pool_ids,
            ext.project,
            'loomy',
            remark=remark or ext.remark,
            group_id=group_id,
        )
        if n > 0:
            return _assign_success_message(ext.project, n, pool_ids=pool_ids)

    if ext.candidates:
        fuzzy_targets = [(p, s) for p, s in ext.candidates if is_wa_classify_target(p)]
        if fuzzy_targets:
            from app.services.loomy_wa_pick_store import store_loomy_wa_pick_options
            from app.services.project_ai_resolve_service import _build_classify_list_message

            store_loomy_wa_pick_options(
                phone=phone,
                group_id=group_id,
                candidates=fuzzy_targets,
                pool_ids=pool_ids,
            )
            return _build_classify_list_message(site, fuzzy_targets)

    return (
        f'找不到活躍專案編號「{site}」。'
        f'請發 *projects* 查看列表，或回覆完整 NAS 資料夾名稱。'
    )
