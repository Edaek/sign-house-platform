# Loom 平台需求：Sign House WA MCP（per-user JWT）

> 给 Loom / Jeff：Sign House 仓库无法实现「Mattermost 用户 → 该用户的 Connection token」；需在 Loom runtime 完成。

## 背景

- MCP URL：`https://signhouse-v3-mcp.it9up.com/mcp`（Streamable HTTP）
- Sign House 已支持：请求头 `Authorization: Bearer <Sign House JWT>` → 调 `/api/wa/*`（RBAC 与 Web 一致）
- 现状：Connections 页 **Connected** 但 Personal Bot `@signhouseloomy` 调用工具时 **未带 Bearer** → `SIGN_HOUSE_JWT is not set`
- 另：`personal-bot has no owner Mattermost user id` 阻碍按用户解析身份

## 必须行为

1. Mattermost 用户 **A** 与 `@signhouseloomy` 对话时，Loom 调用 SHARED **`wa`** MCP 的 **每一次** HTTP 请求（含 `tools/call`）必须带 **A 在 Loom 为 wa 保存的 Bearer JWT**。
2. 修复 **Personal Bot owner**：Mattermost user id ↔ Loom user ↔ 该用户的 wa connection token。
3. **Connected** 语义：表示「当前 Loom 用户的 token 已保存且会被转发」，而非仅 MCP URL 可达。
4. Token 过期：提示用户重新登录 Sign House 并更新 Connections（不要静默失败为 generic JWT 错误）。

## 产品模型（二选一）

| 模型 | 描述 |
|------|------|
| **A（推荐）** | Org 共用 MCP URL；token **按 Loom 用户分表**（非 Connections UI 单一全局 token） |
| **B** | 每人独立 Connection 实例（同 URL）；Bot 按当前 MM 用户选实例 |

## Sign House 侧配合

- 生产 env：`MCP_AUTH_MODE=user`，**不**配置 `SIGN_HOUSE_JWT` / `MCP_BOT_*`
- 日志：`auth_source=user_bearer jwt_sub=...`（不记录 token 原文）

## 验收用例

| # | 步骤 | 预期 |
|---|------|------|
| 1 | 用户 A 绑 JWT，`wa_whoami` | 返回 A 的 email |
| 2 | 用户 B 绑不同 JWT，同一 Bot | 返回 B 的 email |
| 3 | Coolify `MCP_AUTH_MODE=user`，无 server JWT | A/B 均成功，权限不同（如 B 非 manager → NAS 403） |
| 4 | A 的 token 过期 | Loom 提示 A 更新 token；B 不受影响 |
| 5 | Runtime Logs | 无 `auth_source=server_env` / `bot_login`（生产无兜底 env 时） |

## 参考

- 内勤操作：[LOOM_WA_MCP.md](./LOOM_WA_MCP.md)
- MCP 部署：[DEPLOYMENT_MCP.md](../DEPLOYMENT_MCP.md)
