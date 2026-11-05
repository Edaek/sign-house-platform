"""Rule-based WhatsApp replies before Ollama (date, NAS status, greeting, weather)."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from app.services.loomy_wa_nas_summary import format_wa_nas_summary_zh
from app.services.wa_time import hk_datetime_display, wa_now

_DATE_PATTERNS = (
    re.compile(r'今天|今日|几月几号|幾月幾號|什么日期|什麼日期|日期|星期几|星期幾|周几|週幾', re.I),
    re.compile(r'what\s+day|what\s+date|today\'?s?\s+date', re.I),
)

_STATUS_PATTERNS = (
    re.compile(r'状态|狀態|怎么样|怎麼樣|正常吗|正常嗎|連線|连线|nas|共享盘|共享盤|挂载|掛載', re.I),
)

_GREETING_PATTERNS = (
    re.compile(r'^(hi|hello|hey|嗨|你好|您好|在吗|在嗎|在不在)[\?!\.]*$', re.I),
)

_WEATHER_PATTERNS = (
    re.compile(r'天气|天氣|weather|下雨|會下雨|会下雨', re.I),
)

_DISMISS_PATTERNS = (
    re.compile(
        r'不需要归类|不需要歸類|不用归类|不用歸類|不用分类|不用分類'
        r'|不进行归类|不進行歸類|不要归类|不要歸類'
        r'|只是发图|只是發圖|just\s*sharing|no\s*classif'
        r'|不用了|取消归类|取消歸類|不归类|不歸類|^不用$',
        re.I,
    ),
)


def loomy_deterministic_enabled() -> bool:
    raw = (os.environ.get('LOOMY_WA_DETERMINISTIC') or '1').strip().lower()
    return raw not in ('0', 'false', 'no', 'off')


def _normalized_user_text(ctx: Dict[str, Any]) -> str:
    return ((ctx.get('user_text') or ctx.get('caption') or '')).strip()


def _open_pool_query(phone: str, group_id: Optional[str]) -> dict:
    from app.services.pool_receipt_notify_service import phone_match_query

    q: dict = {'projectId': {'$exists': False}, 'dismissed': {'$ne': True}}
    if phone:
        q.update(phone_match_query(phone))
    if group_id:
        q['chatJid'] = {'$regex': group_id.replace('+', r'\+'), '$options': 'i'}
    return q


def _open_pool_count(phone: str, group_id: Optional[str]) -> int:
    if not phone and not group_id:
        return 0
    from app import mongo

    return mongo.db.pool_images.count_documents(_open_pool_query(phone, group_id))


def dismiss_open_pool(phone: str, group_id: Optional[str]) -> int:
    """Mark all open pool images for this sender as dismissed. Returns count."""
    if not phone and not group_id:
        return 0
    from app import mongo

    q = _open_pool_query(phone, group_id)
    now = wa_now()
    result = mongo.db.pool_images.update_many(
        q,
        {'$set': {'dismissed': True, 'dismissedAt': now, 'updatedAt': now}},
    )
    return result.modified_count


def is_dismiss_intent(text: str) -> bool:
    """Check if user text expresses intent to skip/dismiss pool classify."""
    t = (text or '').strip()
    if not t:
        return False
    return any(p.search(t) for p in _DISMISS_PATTERNS)


def try_deterministic_loomy_reply(ctx: Dict[str, Any]) -> Optional[str]:
    if not loomy_deterministic_enabled():
        return None
    text = _normalized_user_text(ctx)
    if not text:
        return None
    if len(text) > 200:
        return None

    if is_dismiss_intent(text):
        phone = (ctx.get('phone') or '').strip()
        group_id = (ctx.get('group_id') or '').strip() or None
        from app.services.loomy_wa_smart_classify import try_dismiss_scoped

        agent_extra = ctx if isinstance(ctx, dict) else {}
        return try_dismiss_scoped(
            phone=phone,
            group_id=group_id,
            text=text,
            quoted_msg_id=(agent_extra.get('quoted_msg_id') or '').strip() or None,
            has_quoted=bool(agent_extra.get('has_quoted')),
        ) or '照片已收到，沒問題，不進行歸類。'

    if any(p.search(text) for p in _WEATHER_PATTERNS):
        return (
            '我沒有連接即時天氣 API，請用天氣 App 查看。'
            '需要歸類工地照片或查專案，可發 *projects* 或 *help*。'
        )

    if any(p.search(text) for p in _DATE_PATTERNS):
        return f'系統日期（香港）：{hk_datetime_display()}。'

    if any(p.search(text) for p in _STATUS_PATTERNS):
        from app.services.nas_watcher_service import nas_mount

        phone = (ctx.get('phone') or '').strip()
        group_id = (ctx.get('group_id') or '').strip() or None
        st = dict(nas_mount.status())
        pool_n = _open_pool_count(phone, group_id)
        return format_wa_nas_summary_zh(st, open_pool_count=pool_n)

    plain = re.sub(r'[^\w\u4e00-\u9fff]', '', text.lower())
    if any(p.match(text.strip()) for p in _GREETING_PATTERNS) or plain in {
        'hi', 'hello', 'hey', '嗨', '你好', '您好', '在吗', '在嗎', '在不在',
    }:
        return (
            f'你好，我是 Signhouse Loomy。系統日期（香港）：{hk_datetime_display()}。\n'
            '可協助：相片歸類到專案、*projects* 列表、*help* 使用說明。'
        )

    return None
