# WhatsApp 归类 → Loom Platform HTTP（方案 A，与 Jeff 2026-03 对齐）

## 架构结论（已锁定）

| 项 | 决定 |
|----|------|
| 入口 | **Sign House Gateway + Wakka** 独占 WhatsApp 收/发；**signhouseloomy 不直连 WhatsApp** |
| Loom MCP | **不需要**（项目列表由 Sign House 随请求带上 `projectCatalogue`） |
| 执行 | **Loom 判** → HTTP 返回 `reply_zh` + 可选 `actions` → **Sign House 进程内执行** `wa_assign_pool_images` 等 |
| 多轮 | **Sign House 维护**（`pendingAssignment` + `session_id`）；工人回「AS-2」等时带上 pending |

**不要** Sign House 与 Loom 同时订阅同一 WhatsApp 号码（会双回、绕过 Gateway 4s 合并）。

---

## 启用（Sign House `.env`）

```env
WA_INBOUND_CLASSIFY_MODE=agent
LOOMY_WA_LOOM_PLATFORM_CLASSIFY=true
LOOM_PLATFORM_CHAT_URL=...
LOOM_PLATFORM_SERVICE_TOKEN=...    # Loom 发的 integration token（待 Jeff 提供长期机器凭证）
LOOM_PLATFORM_BOT_ID=signhouseloomy
LOOMY_WA_LOOM_PLATFORM_FALLBACK_LOCAL=true
```

工人 **无需** JWT。**Loom 不必连 Sign House MCP**（无第二把钥匙、无 JWT 24h 过期问题）。

---

## 请求（Sign House → Loom）

`POST {LOOM_PLATFORM_CHAT_URL}`  
`Authorization: Bearer {LOOM_PLATFORM_SERVICE_TOKEN}`

```json
{
  "bot": "signhouseloomy",
  "channel": "whatsapp_pool_classify",
  "session_id": "wa:p:85296364202",
  "message": "AS-2",
  "poolImageIds": ["..."],
  "pendingAssignment": {
    "poolImageIds": ["..."],
    "askedAt": "2026-03-27T04:00:00Z",
    "previousDecision": "列出候选专案…"
  },
  "projectCatalogue": [
    { "code": "1005", "name": "Site …" },
    { "code": "PJ-1006", "name": "…" }
  ],
  "context": {
    "intent": "pool_classify",
    "phone": "85296364202",
    "group_id": null,
    "pool_image_ids": ["..."],
    "projectCatalogue": [ { "code": "1005", "name": "…" } ],
    "pendingAssignment": { }
  }
}
```

- 顶层 **`poolImageIds`** 与 `context.pool_image_ids` 一致（Jeff 兼容）。
- **`projectCatalogue`**：每次请求从 Mongo **现查** `{code, name}`（非 archived 项目）；Loom **不缓存**；Sign House 保证时效（Sync NAS / 建项目后下一请求即含新 code）。可选 `LOOMY_WA_PROJECT_CATALOGUE=false` 关闭；`LOOMY_WA_PROJECT_CATALOGUE_MAX=N` 限条数（0=不限，仅调试）。
- 多轮追问时 **必须带 `pendingAssignment`**（Sign House 从 `wa_system` 读写，见 `loomy_loom_pending_state.py`）。

---

## 响应（Loom → Sign House）

**权威文案（直接发 WhatsApp）：**

```json
{ "reply_zh": "…" }
```

**兼容：**

```json
{ "reply": { "text": "…", "zh": "…" } }
```

**可选执行（Sign House 本机跑，不要求 Loom MCP 写权限）：**

```json
{
  "reply_zh": "✅ 已归类…",
  "actions": [
    {
      "tool": "wa_assign_pool_images",
      "arguments": {
        "phone": "85296364202",
        "image_ids": ["..."],
        "project_id": "…",
        "notify_whatsapp": true
      }
    }
  ]
}
```

**多轮未结束时可返回：**

```json
{
  "reply_zh": "请回复 AS-1 或 AS-2…",
  "pendingAssignment": {
    "poolImageIds": ["..."],
    "askedAt": "…",
    "previousDecision": "…"
  }
}
```

Sign House 会持久化 `pendingAssignment`；assign 成功或 `actions` 含 assign 后清除。

---

## 9 张图与 Gateway

- **群聊**：默认 **4s burst 合并** → 一次 inbound、一次 Loom、`poolImageIds` 最多 9 个。
- **私聊**：不合并 → 可能多次 inbound；多轮靠 `pendingAssignment` + 引用提醒。

---

## 阶段路线

1. **现在**：Jeff 轻量 HTTP（纯计算 + `projectCatalogue`）；Sign House 执行 assign。  
2. **后续**：同一 HTTP 入口改走 **Loomy runtime + signhouseloomy 本体**（Sign House 契约可不变）。

---

## 待 Jeff

- [ ] `LOOM_PLATFORM_CHAT_URL` + **长期** `LOOM_PLATFORM_SERVICE_TOKEN`（或专用 bot 自动续期）  
- [ ] 响应稳定带 `reply_zh`；多轮时带 `pendingAssignment`  
- [ ] 不在 WhatsApp 侧并行订阅同一号码  

Sign House 桥接代码：`app/services/loomy_loom_platform_bridge.py`。
