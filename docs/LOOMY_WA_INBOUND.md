# Signhouse Loomy — WhatsApp MCP 工具循环（`WA_INBOUND_CLASSIFY_MODE=agent`）

## 架构

```
工人 WhatsApp（群/私聊）→ Gateway → wa_inbound
  → 收图进 media pool
  → 关闭旧规则 bot（模糊 1/2、AI 确认、receipt 洗版）
  → Loomy MCP Agent（Ollama ReAct，最多 LOOMY_WA_MCP_MAX_ROUNDS 轮）
  → 进程内 SignHouseClient + SIGN_HOUSE_JWT 调 /api/wa/*
  → WhatsApp 回繁中短句（reply_zh；不用 wa_send_message 工具）
  → assign 时 API 侧可选 ✅ 归类确认
```

与 Mattermost Signhouse Loomy **同源 MCP 能力**（读 NAS/图池/专案、`wa_assign_pool_images` 等），但运行在 **WhatsApp 通道**，工具有 **白名单**（见 `mcp_wa/wa_tool_registry.py`）。

**不依赖 Mattermost**。Mattermost Webhook 仅可选（`LOOMY_MATTERMOST_NOTIFY=true`）。

## 环境变量

```env
WA_INBOUND_CLASSIFY_MODE=agent
# 或 loomy（同 agent）

# 默认无需 SIGN_HOUSE_JWT：归类/NAS/专案列表走进程内工具（LOOMY_WA_INPROCESS_TOOLS=true）
LOOMY_WA_INPROCESS_TOOLS=true
# 若需 wa_update_record_field 等 HTTP 工具，可选：
# SIGN_HOUSE_JWT=eyJ...  或  MCP_BOT_EMAIL + MCP_BOT_PASSWORD
SIGN_HOUSE_INTERNAL_API_URL=http://127.0.0.1:5010/api

OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_TEXT_MODEL=gemma3:4b

LOOMY_WA_MCP_MAX_ROUNDS=3
# LOOMY_WA_MCP_TOOLS_ALLOW=wa_xxx   # 逗号分隔，追加允许
# LOOMY_WA_MCP_TOOLS_DENY=wa_xxx    # 逗号分隔，追加禁止

LOOMY_WA_AGENT_DEBOUNCE_S=3
GROUP_REMINDER_ENABLED=false
POOL_REMINDER_ENABLED=false
```

默认 `LOOMY_WA_INPROCESS_TOOLS=true` 时 **不必** 配置 JWT；仅当关闭进程内工具且既无 JWT 也无 `MCP_BOT_*` 时，启动日志 ERROR 且工人收到鉴权提示。

## 行为

| 场景 | 行为 |
|------|------|
| 发图 + caption | Agent 调 `wa_list_pool_images` + `wa_assign_pool_images`（含 `nas_folder_name` / `notify_whatsapp` + `group_id`） |
| 同站点多物理文件夹 | Agent 追问，工人回 **1–9**（若已写入 `wa_system` 选项则 `try_loomy_numeric_pick`） |
| 「NAS 连了吗」 | 先 `wa_get_nas_status`，再据结果回答 |
| 天气等通用问题 | 可简短回答 + disclaimer，仍可继续查图池 |
| help / projects / move / keywords | 由 Loomy 调 MCP 工具回答（不再发固定模板） |
| WA record 补资料（followup） | 注入 `active_wa_record` 上下文；`wa_get_record` / `wa_update_record_field` |
| hi、闲聊 | 同一 MCP 循环（非单独 chat-only JSON） |

默认 **禁止**：双向 NAS sync、删专案/删池、confirm/void、`wa_send_message` 等破坏性/内勤操作。

Persona 见 [WA_BOT_PERSONA.md](./WA_BOT_PERSONA.md)。

## 验收（手动）

1. 私聊/群发「今天天气如何」→ 有繁中回复（可带 disclaimer），不再固定拒答。
2. 问「NAS 连了吗」→ 与 Web / `wa_get_nas_status` 一致。
3. 发图 + `3051 …` → 工具链归类或编号追问，文案与 NAS 路径一致。
4. JWT 过期或未配置 → WA 收到明确提示更新 `SIGN_HOUSE_JWT`。

## 运维

- Ollama 不可用时一句兜底，不会卡死 inbound。
- 生产需 Ollama、backend、有效 JWT 同网可达。
