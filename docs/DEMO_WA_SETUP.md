# Demo Mini — WhatsApp（Pool + 仅 Loomy 回复，避免双 bubble）

## 目标架构（方案 B）

```text
工人 WhatsApp → Wakka → Sign House Gateway → Media Pool / POST Loom notify
Loom Turn → /mcp/ → Sign House → Loom 发唯一一条 WhatsApp
```

同一 WhatsApp 号码 **只能一个 Wakka 消费者** 收消息。禁止 **Gateway + Loom NOps Wakka** 并行收同一号码（会双回复，且两条文案可能矛盾）。

---

## 部署 checklist

### 1. Wakka 单消费者（`wakka-single-consumer`）

- [ ] Wakka 上该会话的 webhook / Socket 订阅 **只**指向 Sign House（Mini 上 `python run.py --all`，`PORT=5001`）。
- [ ] **NOps / Loom**：**关闭** 同一号码的 **Wakka 收消息**（或断开 Loom 侧 WhatsApp 入站）。Loom 只通过 **`LOOM_WA_INBOUND_NOTIFY_URL`** 收 Sign House 转发的上下文。
- [ ] 未关 Loom Wakka 前，同一张带 caption 的图（如 `1005`）会进 Pool **一次**，但 Loom 仍可能跑 **两轮 Turn** → 两条 ~Axilogy。部署含 `duplicateInboundTurn` 的版本后，第二轮 `wa_list_pool_images` 应 SILENCE。

### 2. Demo `.env`（`enable-loom-notify`）

见 [backend/.env.example](../backend/.env.example) Demo Mini 块。必填：

```env
SIGNHOUSE_WA_BRAIN=loom
SIGNHOUSE_WA_GATEWAY=true
LOOMY_WA_INPROCESS_TOOLS=false
LOOMY_WA_SIGNHOUSE_SEND=false
LOOMY_WA_MCP_BLOCK_DIRECT_SEND=true
LOOM_WA_RELAY_WHATSAPP_REPLY=false
LOOM_WA_INBOUND_NOTIFY_URL=<从 Loom/NOps 索取>
LOOM_WA_INBOUND_NOTIFY_BEARER=<若需要>
```

`LOOM_WA_INBOUND_NOTIFY_*` 向 Loom 运维（Horsy）索取；填好后重启 `run.py --all`。

### 3. 勿跑 mcp Gateway（`stop-mcp-gateway`）

- [ ] Demo Mini 上 **不要** 运行 `sign-house-v3-mcp` 的 `python run.py --all`（`WA_INBOUND_CLASSIFY_MODE=agent` 会用 **同一 `WAKKA_API_KEY`** 发卡，显示名也可为 ~Axilogy）。
- [ ] 检查进程：`pgrep -fl 'run.py' | grep -E 'sign-house|5010|5001'`

### 4. 验收（`verify-logs-status`）

```bash
# 状态（期望 doubleReplyRisk=low、loomInboundNotifyUrlConfigured=true）
curl -s http://127.0.0.1:5001/api/wa/brain/status | python3 -m json.tool

# 或仓库脚本
./scripts/wa_brain_check.sh http://127.0.0.1:5001
```

发一条 **测试文字** 后，在 backend 日志中 **不应** 出现：

- `[Wakka] Sign House →`（brain=loom 下 Sign House 不代发）
- `[LoomNotify] Sent WA reply`（`LOOM_WA_RELAY_WHATSAPP_REPLY=false` 时不应 relay）

NOps：**一条 In → 一条 Out**；WhatsApp 群 **一条** ~Axilogy 回复。

### 5. Loom Persona（`loom-persona-single-reply`）

在 signhouseloomy 系统提示中（见 [WA_BOT_PERSONA.md](./WA_BOT_PERSONA.md) 第七节）：

- **每轮工人只应看到一条 WhatsApp**。
- **先跑完 MCP**，再用 **一条** 消息说明结果（路径 / 成功 / 需用户选择 bucket）。
- **禁止**先发「收到 / 正在做 / 我先去读档」再发「搞掂」两条（除非工人明确要求进度）。
- 若 MCP 返回 `duplicateInboundTurn: true`：**不要发 WhatsApp**。

---

## 相关文档

- [LOOM_WA_MCP.md](./LOOM_WA_MCP.md)
- [WA_BOT_PERSONA.md](./WA_BOT_PERSONA.md) 第六节方案 B
- `GET /api/wa/brain/status` — `duplicateReplyHints`、`wakkaConsumerChecklist`
