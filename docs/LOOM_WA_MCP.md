# Loom（Signhouse Loomy）+ WA MCP

## 目标架构（signhouseloomy + 工人 WhatsApp）

**定案：Wakka 直接 push 到 Loom → signhouseloomy Turn；Sign House 提供 MCP/API 执行归类。**

```
工人 WhatsApp
  → Wakka（Loom/NOps 上配置，非 Sign House Gateway）
  → Loom Turn（signhouseloomy）
  → org JWT → https://HOST/mcp/（wa_assign_pool_images、wa_list_projects…）
  → 回复经 Loom 同一 Wakka session（或 MCP wa_send_*）
```

| 组件 | 职责 |
|------|------|
| **Loom + Wakka** | 收/发 WA、Turn、大脑 |
| **Sign House** | Mongo 图池/专案、NAS、**MCP 工具**（已写好的归类程序） |
| **Sign House Gateway** | **不要**与 Loom 同号双开（`SIGNHOUSE_WA_GATEWAY=false`） |

同一 WA 号码 **只能一个消费者**：要么 Gateway（旧方案 B），要么 Loom Wakka（方案 A）。

---

## Sign House 配置（demo / mini）

```env
WA_INBOUND_CLASSIFY_MODE=loom
MCP_AUTH_MODE=user
SIGNHOUSE_WA_GATEWAY=false

# 不要在本机再跑 Wakka Gateway（run.py 不要 --all，或 --all 且 GATEWAY=false 只起 API）
# 可不设 LOOM_WA_INBOUND_NOTIFY_*（Wakka 已喂 Loom）
# 不要设 SIGN_HOUSE_JWT / MCP_BOT_*（token 只在 Loom Connections → wa）
```

启动：

```bash
cd backend && source .venv/bin/activate
export PYTHONPATH=.
python run.py          # 仅 API + /mcp/
# 或：python run.py --all  # 在 SIGNHOUSE_WA_GATEWAY=false 时同样只起 API
```

Loom：

1. **NOps / signhouseloomy**：配置 **Wakka**（URL、key、与 852… 会话一致）— 入口问 Horsy。  
2. **Connections → wa**：`https://signhousedemo.cynthai.com/mcp/` + `mint_mcp_token.py` 的 org JWT。  
3. 验证：WA **私聊**发一句 → Loom **Turns** 出现；再测群 / @ 规则。

---

**sign-house-v3** 的 `wa_inbound` 已移除本地 agent / `*help*` / move 等旧 bot 回复路径；仅 **入库 + Loom defer**。本地 Ollama agent 请用 **sign-house-v3-mcp** 或坚持 `SIGNHOUSE_WA_BRAIN=agent` 的旧分支（不推荐与 demo Loom 同 Wakka）。

## 备选：Wakka 仍在 Sign House（Jeff 文档 Gateway 独占）

若暂时 **不能** 把 Wakka 移到 Loom：

```env
SIGNHOUSE_WA_GATEWAY=true
LOOM_WA_INBOUND_NOTIFY_URL=…
LOOM_WA_INBOUND_NOTIFY_BEARER=…
python run.py --all
```

Sign House 收到 inbound 后 **POST** Loom。见 `LOOM_WA_PLATFORM_BRIDGE.md` 与 `loomy_loom_inbound_notify.py`。

---

## Token

### 工人 WhatsApp（org token）

- Loom **Connections → wa** 一条长期 JWT（`mint_mcp_token.py --role manager`）。  
- 工人 **不需要** JWT；`phone` / `group_id` 在 MCP 工具参数里。

### Mattermost 内勤（可选 per-user）

- 每人自己的 JWT → `wa_whoami` 为本人。见 [LOOM_PLATFORM_REQUIREMENTS.md](./LOOM_PLATFORM_REQUIREMENTS.md)。

---

## 内勤 SOP（Wakka → Loom）

1. Mint org token → Loom Connections → wa。  
2. Horsy 在 signhouseloomy 接 Wakka。  
3. Mini：`SIGNHOUSE_WA_GATEWAY=false`，`python run.py`。  
4. MM 测 MCP；WA 测 Turns + 归类。

---

## 内勤 SOP（per-user，Mattermost）

1. Sign House Web 登录 → JWT → Loom Connections → wa。  
2. `@signhouseloomy` → `wa_whoami` 见本人 email。

---

## 过渡方案（deprecated）

服务器 `SIGN_HOUSE_JWT` / `MCP_BOT_*`、`MCP_AUTH_MODE=fallback` — 见下文「迁移」。

---

## 自测

```bash
curl -s https://HOST/api/mcp/hosted-wa/status
```

---

## 故障

| 现象 | 处理 |
|------|------|
| WA 无 Turn，Sign House 有 Gateway 日志 | Wakka 还在喂 Sign House；改 **Wakka→Loom** 并 `SIGNHOUSE_WA_GATEWAY=false` |
| Turn 有，归类失败 | Loom Connections token、MCP URL 尾斜杠 `/mcp/` |
| MM 通、WA 不通 | 群 JID / @ 规则；Loom Wakka 配置 |
| Loom 能看到图，**Media Pool 没有** | 必须 **Gateway 入 pool**（`SIGNHOUSE_WA_GATEWAY=true` + `run.py --all`）；仅 Loom Wakka 不会写 `pool_images` |
| 备注在 Web 有，**NAS 无 .txt** | 部署含 `remark`/`site-remark`/`site_note_from_text` 的后端；Loom 须 `wa_assign_pool_images(remark=…)`，不要用 `wa_update_record_field` |
| Gateway `consumer lease` 报错 | 同机只跑一个 `--all`；或等 lease 过期再启 |

## Demo 部署清单（Pool + txt）

完整步骤见 **[DEMO_WA_SETUP.md](./DEMO_WA_SETUP.md)**（双回复收敛 checklist）。

1. `git pull` 含 remark/txt 与 Gateway 入 pool 修复的版本  
2. Mini：`SIGNHOUSE_WA_GATEWAY=true`，`SIGNHOUSE_WA_BRAIN=loom`，`LOOM_WA_INBOUND_NOTIFY_URL=…`，`python run.py --all`  
3. **Wakka 只推 Gateway**；**NOps 关闭 Loom 同号 Wakka 入站**（勿 Gateway + Loom 双消费）  
4. **勿**在 Demo 跑 `sign-house-v3-mcp` Gateway（同 `WAKKA_API_KEY` 会双发卡）  
5. Loom Connections → wa：org JWT → `https://<demo>/mcp/`  
6. Loom 系统提示：贴 [WA_BOT_PERSONA.md](./WA_BOT_PERSONA.md) 第七节（**每轮一条 WA**）  
7. 验收：`./scripts/wa_brain_check.sh` → `doubleReplyRisk=low`  

---

## Cursor

`Authorization: Bearer` → `https://HOST/mcp/`。本地见 [backend/mcp_wa/README.md](../backend/mcp_wa/README.md).
