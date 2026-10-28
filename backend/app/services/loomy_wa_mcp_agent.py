"""WhatsApp Loomy — MCP tool loop (Ollama ReAct + SIGN_HOUSE_JWT)."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from app.services.ai_extract_service import _get_config, _parse_structured
from mcp_wa.inprocess_client import JWT_MISSING_MSG, try_get_inprocess_client, wa_loomy_tools_ready
from mcp_wa.wa_tool_registry import execute_tool, is_tool_allowed, tool_catalog_for_prompt

logger = logging.getLogger(__name__)

MAX_ROUNDS = int(os.environ.get('LOOMY_WA_MCP_MAX_ROUNDS', '3'))
AGENT_OLLAMA_TIMEOUT = int(os.environ.get('LOOMY_WA_AGENT_TIMEOUT_S', '90'))


def _call_ollama(prompt: str) -> str:
    import requests

    cfg = _get_config()
    resp = requests.post(
        f"{cfg['base_url'].rstrip('/')}/api/generate",
        json={
            'model': cfg['text_model'],
            'prompt': prompt,
            'stream': False,
            'options': {'temperature': 0.25, 'num_predict': 1536},
        },
        timeout=AGENT_OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get('response', '') or ''


def _build_session_block(ctx: Dict[str, Any]) -> str:
    phone = ctx.get('phone') or ''
    group_id = (ctx.get('group_id') or '').strip()
    sender = (ctx.get('sender_name') or '').strip()
    user_text = (ctx.get('user_text') or '').strip()
    caption = (ctx.get('caption') or '').strip()
    pool_ids = ctx.get('pool_ids') or []
    lines = [
        f'sender_phone: {phone}',
        f'sender_name: {sender}',
        f'whatsapp_group_id: {group_id or "(private)"}',
        f'user_message: {user_text or "(none)"}',
        f'media_caption: {caption or "(none)"}',
        f'known_pool_image_ids: {", ".join(pool_ids[:20]) or "(none)"}',
    ]
    if group_id:
        lines.append(
            'When assigning with notify_whatsapp, pass group_id above to wa_assign_pool_images.'
        )
    if phone and not group_id:
        lines.append(
            f'When listing pool for this sender, pass phone={phone} to wa_list_pool_images.'
        )
    quoted = (ctx.get('quoted_msg_id') or '').strip()
    if quoted or ctx.get('has_quoted'):
        lines.append(f'quoted_msg_id: {quoted or "(yes)"}')
    inbound_type = (ctx.get('inbound_type') or '').strip()
    if inbound_type:
        lines.append(f'inbound_type: {inbound_type}')
    record = ctx.get('active_wa_record')
    if isinstance(record, dict) and record.get('record_id'):
        lines.append('active_wa_record: ' + json.dumps(record, ensure_ascii=False))
    move_payload = ctx.get('move_inbound_data')
    if isinstance(move_payload, dict):
        lines.append('move_context: ' + json.dumps(move_payload, ensure_ascii=False))
    from app.services.loomy_wa_deterministic_reply import hk_datetime_display

    lines.append(f'server_time_hk: {hk_datetime_display()}')
    try:
        from app.services.loomy_wa_deterministic_reply import _open_pool_count
        from app.services.nas_watcher_service import nas_mount

        st = dict(nas_mount.status())
        pool_n = _open_pool_count(phone, group_id or None)
        from app.services.loomy_wa_nas_summary import format_wa_nas_summary_zh

        lines.append(f'nas_summary_zh: {format_wa_nas_summary_zh(st, open_pool_count=pool_n)}')
        lines.append(f'open_pool_count: {pool_n}')
    except Exception:
        pass
    return '\n'.join(lines)


def _store_pick_options(
    ctx: Dict[str, Any],
    pick_options: Any,
    pool_ids: List[str],
) -> None:
    if not pick_options or not isinstance(pick_options, list):
        return
    opts = []
    for row in pick_options[:9]:
        if not isinstance(row, dict):
            continue
        pid = (row.get('project_id') or row.get('projectId') or '').strip()
        label = (row.get('label') or '').strip()
        if pid or label:
            opts.append({
                'project_id': pid,
                'label': label,
                'code': (row.get('code') or '').strip(),
            })
    if not opts:
        return
    phone = ctx.get('phone') or ''
    group_id = (ctx.get('group_id') or '').strip() or None
    task = f'g:{group_id}:{phone}' if group_id else f'p:{phone}'
    key = f'loomy_wa_pick:{task}'
    from datetime import datetime

    from app import mongo

    mongo.db.wa_system.update_one(
        {'_id': key},
        {'$set': {'options': opts, 'pool_ids': pool_ids, 'at': datetime.utcnow()}},
        upsert=True,
    )


def _system_preamble() -> str:
    return """You are Signhouse Loomy on WhatsApp (same capabilities as Mattermost Signhouse, via MCP tools).
Reply ONLY in Traditional Chinese (繁體中文) for end users — never Simplified Chinese. Use tools to fetch real data before answering NAS/pool/project questions.
For date/time questions: use server_time_hk from Session — answer directly; do NOT say it is non-real-time.
For NAS status: use nas_summary_zh from Session; if foldersCacheStale is implied, do NOT claim the share has zero folders.
For weather/stock/live external data: briefly say no live API, suggest an app, then offer photo/project help.
For *help*, *projects*, *keywords*: use wa_list_projects, wa_list_keywords, wa_get_pool_stats — do not invent lists.
For *move <project>*: output action move with target_project_label (uses quoted photo or recent assign); explain steps if unclear.
If active_wa_record is set, use wa_get_record and wa_update_record_field to collect missing fields; one question at a time.
For photo classify: use wa_list_pool_images then wa_assign_pool_images with correct project_id and nas_folder_name when duplicates exist.
If the user included a note (备注/備註/text after the project code), pass it as remark on wa_assign_pool_images — note text only. That writes the NAS day .txt. Say the remark was saved only when siteRemarkQueued is true.
If photos were already filed and the user adds a note later, call wa_append_site_remark with project_code and text (same nas folder as the assign).
If media_caption already contains a site/project code (e.g. 2991, PJ-xxxx), resolve via wa_list_projects / wa_get_project and assign — do not ask the user to repeat obvious caption info.
Only one concise reply per turn; do not repeat the legacy「收到照片请回覆专案编码」template.
Do NOT use blocked tools; user-facing text goes in reply_zh (not wa_send_message).
If the user says they don't need classification / just sharing / 不需要归类 / 不用 / 取消归类, output {"action":"dismiss"} — the system will mark pool images as dismissed and confirm.

Output ONE JSON object only:
{"action":"tool","tool":"wa_get_nas_status","arguments":{}}
OR
{"action":"reply","reply_zh":"...","pick_options":[{"project_id":"...","label":"1. ..."}]}
OR
{"action":"move","target_project_label":"PJ-3051"}
OR
{"action":"dismiss"}
When reply_zh lists numbered choices 1–9, include pick_options (same order) for numeric follow-up."""


def run_mcp_agent(ctx: Dict[str, Any], *, send_wa: Callable[[str, Optional[str], str], None]) -> None:
    """Run tool loop; send_wa(phone, group_id, text) delivers WhatsApp message."""
    phone = ctx.get('phone') or ''
    group_id = (ctx.get('group_id') or '').strip() or None
    pool_ids = list(ctx.get('pool_ids') or [])
    caption = (ctx.get('caption') or '').strip()

    if caption and pool_ids:
        from app.services.loomy_wa_mongo_site_classify import try_loomy_mongo_site_classify_reply

        mongo_reply = try_loomy_mongo_site_classify_reply(
            phone=phone,
            caption=caption,
            pool_ids=pool_ids,
            group_id=group_id,
        )
        if mongo_reply:
            send_wa(phone, group_id, mongo_reply)
            return

    if not wa_loomy_tools_ready():
        send_wa(phone, group_id, JWT_MISSING_MSG)
        return

    client = try_get_inprocess_client()

    catalog = tool_catalog_for_prompt()
    transcript: List[str] = [
        _system_preamble(),
        'Allowed tools:\n' + catalog,
        'Session:\n' + _build_session_block(ctx),
    ]

    for round_i in range(MAX_ROUNDS):
        prompt = '\n\n'.join(transcript)
        if round_i > 0:
            prompt += '\n\nContinue: call another tool or reply with action reply.'
        try:
            raw = _call_ollama(prompt)
            data = _parse_structured(raw or '')
        except Exception as exc:
            logger.warning('[LoomyWA/MCP] Ollama round %s failed: %s', round_i, exc)
            send_wa(
                phone,
                group_id,
                '暫時無法連接 AI 服務；請稍後再試，或發 *help* / *projects*。',
            )
            return

        action = (data.get('action') or '').strip().lower()
        if action == 'dismiss':
            from app.services.loomy_wa_deterministic_reply import dismiss_open_pool

            n = dismiss_open_pool(phone, group_id)
            if n > 0:
                send_wa(phone, group_id, f'照片已收到，沒問題，不進行歸類。（已略過 {n} 張）')
            else:
                send_wa(phone, group_id, '照片已收到，沒問題，不進行歸類。')
            return

        if action == 'move':
            from app.services.wa_move_intent_service import execute_move_intent, parse_move_target

            label = (data.get('target_project_label') or data.get('project_label') or '').strip()
            if not label:
                label = parse_move_target(ctx.get('user_text') or '') or ''
            move_data = ctx.get('move_inbound_data')
            if not isinstance(move_data, dict):
                move_data = {
                    'hasQuotedMsg': bool(ctx.get('has_quoted')),
                    'quotedMsgId': ctx.get('quoted_msg_id') or '',
                }
            msg = execute_move_intent(
                phone,
                label,
                move_data,
                group_id=group_id,
            )
            send_wa(phone, group_id, msg)
            return

        if action == 'reply' or data.get('reply_zh'):
            reply = (data.get('reply_zh') or '').strip()
            _store_pick_options(ctx, data.get('pick_options'), ctx.get('pool_ids') or [])
            if reply:
                send_wa(phone, group_id, reply)
            return

        tool = (data.get('tool') or '').strip()
        if action != 'tool' or not tool:
            reply = (data.get('reply_zh') or '').strip()
            if reply:
                send_wa(phone, group_id, reply)
            return

        args = data.get('arguments') or data.get('args') or {}
        if not isinstance(args, dict):
            args = {}

        if not is_tool_allowed(tool):
            transcript.append(f'Tool result ({tool}): not allowed on WhatsApp channel.')
            continue

        result = execute_tool(tool, args, client=client)
        if len(result) > 8000:
            result = result[:7997] + '...'
        transcript.append(f'Tool result ({tool}):\n{result}')
        logger.info('[LoomyWA/MCP] tool=%s round=%s', tool, round_i)

    send_wa(
        phone,
        group_id,
        '處理時間較長，請發 *help* 或重新描述需求（例如專案編號 + 照片說明）。',
    )
