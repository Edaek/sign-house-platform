# Loom（Signhouse Loomy）+ WA MCP

## 目标架构（生产）

Sign House 暴露 **`https://HOST/mcp/`**；Loom 用 **Bearer JWT** 调工具。依场景分两种 token 策略：

### A. 工人 WhatsApp（`WA_INBOUND_CLASSIFY_MODE=loom`）

- 每条 WA inbound 会 **POST** 到 Loom（`LOOM_WA_INBOUND_NOTIFY_URL` 或 `LOOM_PLATFORM_CHAT_URL`）；Loom 跑 agent 后 **`reply_zh` + actions** 或仅用 MCP `wa_send_*` 回工人。
- Sign House **不用**本地 Ollama 抢答。
- Loom **Connections → wa** 配置 **一个** 长期 org token（服务账号，建议 `manager`），**工人不用**各自 JWT。
- 工人是谁：由 Loom 调 MCP 时在工具参数里带 **`phone` / `group_id`**（来自 Gateway inbound），与 JWT 的 `sub` 无关。
- 签发长期 token：`backend/scripts/mint_mcp_token.py --email … --role manager`（见 `.env.example` 的 `MCP_SERVICE_TOKEN_HOURS`）。
- 服务器：**可不设** `SIGN_HOUSE_JWT` / `MCP_BOT_*`；设 **`MCP_AUTH_MODE=user`** 表示只接受 Loom 转发来的那一个 Bearer。

```env
WA_INBOUND_CLASSIFY_MODE=loom
MCP_AUTH_MODE=user
LOOM_WA_INBOUND_NOTIFY_URL=https://loom.example.com/api/wa-inbound   # Jeff 提供
LOOM_WA_INBOUND_NOTIFY_BEARER=…   # 可与 Loom MCP 同一条 org JWT
SIGN_HOUSE_API_URL=http://127.0.0.1:5001/api
```

未配置 notify URL 时启动日志会警告，WhatsApp **不会**自动回复。

### B. Mattermost 内勤（可选 per-user）

- 每位内勤在 Loom 绑 **自己的** JWT → `wa_whoami` 应对应本人 email，RBAC 与 Web 一致。
- 见 [LOOM_PLATFORM_REQUIREMENTS.md](./LOOM_PLATFORM_REQUIREMENTS.md)（Loom 需按 MM 用户选 token）。

---

## 内勤 SOP（org token，WhatsApp / Loom 主路径）

1. 管理员执行 `mint_mcp_token.py`，创建或指定 **专用 MCP 账号**（如 `loom-wa@…`，role `manager`）。
2. [loom.naton.io](https://loom.naton.io) → **Connections → wa** → 粘贴 **这一条** access_token → Connect。
3. Demo/Coolify：`WA_INBOUND_CLASSIFY_MODE=loom`，`MCP_AUTH_MODE=user`，**不要**在服务器再配第二份 `SIGN_HOUSE_JWT`（避免双身份）。
4. Loom 侧：`wa_whoami` 应显示 **服务账号** email；工人 WhatsApp 归类靠 `wa_assign_pool_images(phone=…)` 等参数。

---

## 内勤 SOP（per-user，Mattermost）

1. Sign House Web 登录（本人账号，建议 manager/admin 若需 NAS/keywords）。
2. 复制 JWT：`auth-storage` → `state.token`，或 `/api/auth/login` 的 `access_token`。
3. [loom.naton.io](https://loom.naton.io) → **My Connections → wa** → Your token → **Connect**。
4. Mattermost `@signhouseloomy`：**「执行 wa_whoami，贴原文」** → 应看到你的 **email**。
5. JWT 过期（默认约 24h）→ **本人**更新 Loom token，无需改 Coolify。

---

## 自测后端

```bash
curl -s -m 5 https://signhouse-v3-mcp.it9up.com/api/auth/me
# 401 + Missing Authorization Header（几秒内）
```

---

## 过渡方案（deprecated）

在 Loom **尚未**按 Mattermost 用户转发 Bearer 前，可临时使用服务器兜底。**不应**作为长期方案。

| 方式 | 环境变量 | 说明 |
|------|----------|------|
| 手动 JWT | `SIGN_HOUSE_JWT` | 约 24h 需手换 |
| 机器人自动登录 | `MCP_BOT_EMAIL` + `MCP_BOT_PASSWORD` | 全员同一身份 |

此模式使用 **`MCP_AUTH_MODE=fallback`**（默认）。日志中 `auth_source=server_env` 或 `bot_login` 表示未走用户 Bearer。

---

## 迁移到 per-user（Coolify）

见 [LOOM_PLATFORM_REQUIREMENTS.md](./LOOM_PLATFORM_REQUIREMENTS.md) 验收 Loom 侧完成后：

1. **阶段 2**：2～3 名内勤各绑 Loom token，`wa_whoami` 应返回 **不同** email（与兜底账号不同）。
2. **阶段 3**：设 `MCP_AUTH_MODE=user`，**暂时保留**兜底 env；看 Runtime Logs 是否均为 `auth_source=user_bearer`。
3. **阶段 4**：删除 `SIGN_HOUSE_JWT` / `MCP_BOT_*`，Redeploy；全员完成 Loom 绑定。

---

## 故障

| 现象 | 处理 |
|------|------|
| `MCP_AUTH_MODE=user` + 无 Bearer | 去 Loom Connections 绑 token |
| Loom Connected 仍失败 | Personal Bot 未转发 token → 找 Loom 管理员（见 LOOM_PLATFORM_REQUIREMENTS） |
| 401 / JWT hint | 重新登录 Sign House，更新 Loom token |
| 无 Bearer 仍返回固定 admin | Coolify 仍设 `SIGN_HOUSE_JWT` 或 `MCP_BOT_*` 且 `MCP_AUTH_MODE=fallback` → 见迁移阶段 3/4 |
| MCP URL 用 `/mcp` 无尾斜杠 | 用 **`/mcp/`**；旧部署曾 307 到 `http://…` 并丢 Authorization（Loom PR #32 + 服务端内部 rewrite） |

自检（不暴露 token 值）：

```bash
curl -s https://signhouse-v3-mcp.it9up.com/api/mcp/hosted-wa/status
# 看 mcpAuthMode、serverJwtFallbackConfigured、botLoginFallbackConfigured
```

---

## Cursor

同 Loom：`Authorization: Bearer` 指向 `https://HOST/mcp/`。本地见 [backend/mcp_wa/README.md](../backend/mcp_wa/README.md)。
