"""WhatsApp Loomy — MCP tool loop (Ollama ReAct + SIGN_HOUSE_JWT)."""
from __future__ import annotations

from app.services.wa_time import wa_now

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
    from app.services.wa_time import hk_datetime_display

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
        {'$set': {'options': opts, 'pool_ids': pool_ids, 'at': wa_now()}},
        upsert=True,
    )


def _system_preamble() -> str:
    return """You are Signhouse — a teammate on WhatsApp, not a customer-service bot. Reply ONLY in Traditional Chinese (繁體中文) for workers; short mobile-style sentences; no "I'm an AI"; no repeating the user's whole question. Use MCP for facts before answering NAS/pool/project questions.

Inbound intent (every message — do not skip MCP for memory-only / cheap paths):
- Single digit 1–9 ONLY when you listed numbered choices last turn → pick_options assign (with nas_folder_name + nas_parent_bucket).
- Site codes: bare 3–6 digits, 3014A, PJ-3026, PJ 3026, P1005, etc. → wa_list_pool_images → wa_list_projects (+ wa_browse_nas) → list 1/2 with FULL folder names if ambiguous → wa_assign_pool_images. NOT the same as menu digit 1–9 (1005 is a site, not "option 5").
- Full NAS folder label on disk → verify wa_get_project then assign with matching nas_folder_name.
- User corrects project ("不是這個 PJ" / wrong site) → re-list all folders for that site; do not reuse wrong project_id.
- Photo with no caption → list_pool then ONE message asking for site or full folder name; no interim "going to check pool" second bubble.
- NAS status / hi / @bot → wa_get_nas_status or brief 在; merge with pool classify in one turn if both apply.
- Remark after assign → wa_append_site_remark only (not wa_update_record_field for classify txt).

Before assign: wa_list_pool_images(unassigned). If the user's photo is not in the list, say it is not in Media Pool yet — do not guess download queues or claim success.
Classify: wa_assign_pool_images with remark = note text ONLY (e.g. user「歸到1005備註是 Test」→ remark「Test」). siteRemarkQueued true before saying txt/remark saved. After assign, wa_append_site_remark for late notes. Never wa_update_record_field for classify remarks (no NAS txt).
For date/time questions: use server_time_hk from Session — answer directly; do NOT say it is non-real-time.
For NAS status: use nas_summary_zh from Session; if foldersCacheStale is implied, do NOT claim the share has zero folders.
For weather/stock/live external data: briefly say no live API, suggest an app, then offer photo/project help.
For *help*, *projects*, *keywords*: use wa_list_projects, wa_list_keywords, wa_get_pool_stats — do not invent lists.
For *move <project>*: output action move with target_project_label (uses quoted photo or recent assign); explain steps if unclear.
If active_wa_record is set, use wa_get_record and wa_update_record_field to collect missing fields; one question at a time.
For photo classify: use wa_list_pool_images then wa_assign_pool_images with correct project_id and nas_folder_name when duplicates exist.
Before wa_create_project for a bare numeric site code (e.g. 1008): call wa_list_projects and wa_browse_nas on the parent bucket. If the exact code is missing but nearby codes exist (1005, 1007), ask the user to pick — do NOT create a new folder until they confirm the number is new.
Group chat assign: wa_list_pool_images(status=unassigned, phone=sender) then wa_assign_pool_images with the same group_id (@g.us) — never mix image_ids from different phones in one assign.
If the user included a note (备注/備註/text after the project code), pass it as remark on wa_assign_pool_images — note text only. That writes the NAS day .txt. Say the remark was saved only when siteRemarkQueued is true.
If photos were already filed and the user adds a note later, call wa_append_site_remark with project_code and text (same nas folder as the assign).
If the user wants to rename the day remark .txt (any basename, not only <folder>_<date>.txt), use wa_rename_site_remark_txt; on duplicate_remark_txt relay message and ask for another name; pass phone so append follows the new name today.
View/edit/delete day txt: wa_read_site_remark_txt (list_all if multiple); wa_set_site_remark_txt to replace body (empty content clears body but keeps file — use to remove「—」placeholder); wa_delete_site_remark_txt to remove file; wa_append_site_remark only adds text.
After wa_rename_nas_site_folder or wa_sync_site_code_from_folder, if remarkTxtMergeOk is false, tell the user folder/code updated but remark txt merge failed (remarkTxtMergeMessage) — do not claim txt files were merged.
If media_caption already contains a site/project code (e.g. 2991, PJ-xxxx), resolve via wa_list_projects / wa_get_project and assign — do not ask the user to repeat obvious caption info.
When the user @mentions Signhouse or pings (在不在、@bot、点 bot 名): always reply briefly that you are here (e.g. 在，Signhouse 喺度。要歸相、補備註定查專案，直接講。) — do NOT SILENCE on @bot. If they ask why an earlier @ had no reply, explain wrong @ (LID like @358… or @ teammate only) vs @ bot number +852 9636 4202; use wa_get_whatsapp_status for connected/token. Mattermost @signhouseloomy: same — always acknowledge.
Only one concise reply per turn; do not repeat the legacy「收到照片请回覆专案编码」template. SILENCE only when you would repeat yourself in a fast back-and-forth with no new ask.
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
