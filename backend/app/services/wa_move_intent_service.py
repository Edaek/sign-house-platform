"""Move assigned pool images to another project (WhatsApp move command / Loomy action)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app import mongo
from app.services.image_pool_service import match_project_ext, move_images_to_project


def parse_move_target(text: str) -> Optional[str]:
    m = re.match(r'^[\/!]?\s*move\s+(.+)$', (text or '').strip(), re.IGNORECASE)
    return m.group(1).strip() if m else None


def quoted_id_variants(quoted_id: str) -> List[str]:
    if not quoted_id:
        return []
    raw = str(quoted_id)
    parts = raw.split('_')
    short_id = parts[2] if len(parts) >= 3 else None
    return [i for i in (raw, short_id) if i]


def find_pool_images_by_quoted_msg(quoted_msg_id: str, sender: str) -> List[dict]:
    if not quoted_msg_id:
        return []
    possible_ids = quoted_id_variants(quoted_msg_id)
    images = list(mongo.db.pool_images.find({
        'messageId': {'$in': possible_ids},
        'phone': sender,
        'projectId': {'$exists': True},
    }))
    if not images:
        for qid in possible_ids:
            images = list(mongo.db.pool_images.find({
                'messageId': {'$regex': re.escape(qid)},
                'phone': sender,
                'projectId': {'$exists': True},
            }))
            if images:
                break
    return images


def find_recent_assigned_pool_images(sender: str, limit: int = 20) -> List[dict]:
    return list(mongo.db.pool_images.find(
        {'phone': sender, 'projectId': {'$exists': True}},
    ).sort('assignedAt', -1).limit(limit))


def execute_move_intent(
    sender: str,
    target_label: str,
    data: Dict[str, Any],
    *,
    group_id: Optional[str] = None,
) -> str:
    """Run move logic; return user-facing Traditional Chinese message (no side-channel send)."""
    label = (target_label or '').strip()
    if not label:
        return (
            '📦 *搬移照片*\n'
            '用法：回覆要搬移的照片並輸入 *move 專案名稱*，或直接 *move 專案名稱* 搬移最近歸類的照片。'
        )

    result = match_project_ext(label, active_only=True)
    new_project = result.project

    if not new_project and result.candidates:
        lines = []
        for i, item in enumerate(result.candidates[:9], 1):
            proj = item[0] if isinstance(item, (list, tuple)) else item
            if isinstance(proj, dict):
                lines.append(f'{i}. {proj.get("code", "")} {proj.get("name", "")}'.strip())
            else:
                lines.append(f'{i}. {item}')
        return (
            f'找到多個專案符合「{label}」，請回覆編號或更完整名稱：\n'
            + '\n'.join(lines)
        )

    if not new_project:
        return f'⚠️ 找不到專案「{label}」。可用 wa_list_projects 或發 *projects* 查看列表。'

    has_quoted = data.get('hasQuotedMsg', False)
    quoted_id = data.get('quotedMsgId')

    if has_quoted and quoted_id:
        images = find_pool_images_by_quoted_msg(quoted_id, sender)
    else:
        images = find_recent_assigned_pool_images(sender, limit=20)
        if images:
            last_record_id = images[0].get('recordId')
            if last_record_id:
                images = [img for img in images if img.get('recordId') == last_record_id]
            else:
                images = images[:1]

    if not images:
        return '⚠️ 找不到可搬移的照片。請回覆要搬移的照片再試一次。'

    if all(img.get('projectCode') == new_project['code'] for img in images):
        return f'ℹ️ 這些照片已經在專案 *{new_project["code"]}* 中，無需搬移。'

    old_codes = list({img.get('projectCode', '?') for img in images})
    image_ids = [str(img['_id']) for img in images]
    move_result = move_images_to_project(image_ids, new_project, moved_by='loomy_agent')

    if move_result['moved'] > 0:
        old_label = ', '.join(old_codes)
        return (
            f'✅ 已成功搬移 *{move_result["moved"]}* 张照片\n'
            f'从 *{old_label}* → *{new_project["code"]}*'
        )

    err_detail = '；'.join(move_result.get('errors', []))
    return f'❌ 搬移失败：{err_detail or "未知错误"}'
