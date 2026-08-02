# wa-bot -> sign-house-v3 完整迁移执行文档

> 将 sign-house-wa-bot 的全部功能迁移到 sign-house-v3，合并为统一的 Flask + React 项目。

---

## 迁移总览

| 类别 | wa-bot (TypeScript) | v3 目标 (Python/React) |
|------|--------------------|-----------------------|
| 后端框架 | Next.js App Router | Flask Blueprint |
| 前端框架 | Next.js RSC + Client | React (Vite) + Zustand |
| ORM | Mongoose | PyMongo (helper 函数) |
| 认证 | NextAuth v5 (JWT cookie) | Flask-JWT-Extended (Bearer token) |
| Gateway | Node.js + socket.io-client | Python + python-socketio[client] |
| AI | Ollama (ollama npm) | Ollama (requests HTTP) |
| 文件传输 | ssh2-sftp-client / child_process | paramiko / subprocess |

---

## 阶段一：依赖安装

### 1.1 Python 依赖（追加到 requirements.txt）

```
# WhatsApp / Gateway
python-socketio[client]==5.11.1
requests>=2.31.0

# File transfer
paramiko>=3.4.0
scp>=0.15.0

# AI (Ollama)
# (使用 requests 直接调用 Ollama HTTP API，无需额外包)

# Image processing (群组提醒合成缩略图，替代 sharp)
# Pillow 已在 requirements.txt 中
```

### 1.2 前端依赖（追加到 frontend/package.json）

```bash
# 无需额外 npm 包，使用现有 Tailwind + lucide-react + react-hot-toast
```

---

## 阶段二：MongoDB 模型迁移

### 源文件 → 目标文件映射

所有模型 helper 追加到 `backend/app/models/__init__.py`。

| # | wa-bot 模型文件 | 行数 | 新增 Python 函数 | 集合名 |
|---|----------------|------|-----------------|--------|
| 1 | `src/models/record.ts` | 165 | `create_wa_record_doc()`, `wa_record_to_dict()` | `wa_records` |
| 2 | `src/models/project.ts` | 57 | `create_wa_project_doc()`, `wa_project_to_dict()` | `wa_projects` |
| 3 | `src/models/pool-image.ts` | 52 | `create_pool_image_doc()`, `pool_image_to_dict()` | `pool_images` |
| 4 | `src/models/group-pending-image.ts` | 50 | `create_group_pending_image_doc()`, `group_pending_image_to_dict()` | `group_pending_images` |
| 5 | `src/models/keyword.ts` | 32 | `create_keyword_doc()`, `keyword_to_dict()` | `wa_keywords` |
| 6 | `src/models/template.ts` | 49 | `create_wa_template_doc()`, `wa_template_to_dict()` | `wa_templates` |
| 7 | `src/models/organization.ts` | 36 | `create_organization_doc()`, `organization_to_dict()` | `wa_organizations` |
| 8 | `src/models/pending-photo.ts` | 19 | `create_pending_photo_doc()` | `wa_pending_photos` |
| 9 | `src/models/audit-log.ts` | 29 | (复用 v3 已有 `create_audit_log_doc()`) | `audit_logs` |
| 10 | `src/models/user.ts` | 31 | (复用 v3 已有 `create_user_doc()`) | `users` |

### 索引创建

追加到 `backend/app/__init__.py` 的 `create_app()` 中：

```python
# WA collections indexes
mongo.db.wa_records.create_index('referenceNumber', unique=True)
mongo.db.wa_records.create_index('project')
mongo.db.wa_records.create_index('status')
mongo.db.wa_records.create_index('createdAt')
mongo.db.wa_projects.create_index('code', unique=True)
mongo.db.pool_images.create_index('assignedAt', expireAfterSeconds=30*24*3600)
mongo.db.group_pending_images.create_index('batchId')
mongo.db.wa_keywords.create_index([('type', 1), ('value', 1)], unique=True)
mongo.db.wa_pending_photos.create_index('createdAt', expireAfterSeconds=3600)
```

---

## 阶段三：后端服务层迁移

### 源文件 → 目标文件映射

所有服务放到 `backend/app/services/`。

| # | wa-bot 源文件 | 行数 | 新建 Python 文件 | 功能说明 |
|---|--------------|------|-----------------|---------|
| 1 | `src/lib/wa-send.ts` | 187 | `wa_send_service.py` | Wakka REST API：发消息/媒体/群消息、下载媒体、查询会话/token |
| 2 | `src/lib/image-pool.ts` | 330 | `image_pool_service.py` | 图片池：保存/匹配项目/分配/提醒/创建Record/上传NAS |
| 3 | `src/lib/nas-upload.ts` | 169 | `nas_upload_service.py` | paramiko SFTP 上传到客户 NAS |
| 4 | `src/lib/mini-transfer.ts` | 140 | `mini_transfer_service.py` | subprocess SSH/SCP 传图到 Mac Mini |
| 5 | `src/lib/extraction-runner.ts` | 72 | `extraction_runner_service.py` | 对 Record 运行 AI 提取，推进状态 |
| 6 | `src/lib/followup.ts` | 212 | `followup_service.py` | 自动/手动跟进：检测缺失字段、Ollama生成问题、WhatsApp发送 |
| 7 | `src/lib/ai/extract.ts` | 206 | `ai_extract_service.py` | 调用 Ollama HTTP API 提取结构化字段 |
| 8 | `src/lib/ai/prompts.ts` | 144 | `ai_prompts.py` | prompt 模板（提取/跟进/图像分析） |
| 9 | `src/lib/reference-number.ts` | 34 | `reference_number_service.py` | 生成 SUB-MMDD-NNN 参考号 |
| 10 | `src/lib/parser.ts` | 145 | `message_parser_service.py` | WhatsApp 消息解析：项目代码/关键词/命令 |

### 服务依赖关系

```
wa_send_service ← image_pool_service, followup_service, extraction_runner_service
ai_extract_service ← extraction_runner_service
ai_prompts ← ai_extract_service, followup_service
nas_upload_service ← image_pool_service
mini_transfer_service ← (inbound API 直接调用)
message_parser_service ← image_pool_service, (inbound API)
reference_number_service ← image_pool_service, (inbound API)
```

### 实现顺序（按依赖）

1. `ai_prompts.py` (无依赖)
2. `reference_number_service.py` (仅依赖 MongoDB)
3. `message_parser_service.py` (仅依赖 MongoDB)
4. `wa_send_service.py` (依赖 requests + env vars)
5. `nas_upload_service.py` (依赖 paramiko)
6. `mini_transfer_service.py` (依赖 subprocess)
7. `ai_extract_service.py` (依赖 ai_prompts + requests)
8. `extraction_runner_service.py` (依赖 ai_extract_service)
9. `followup_service.py` (依赖 wa_send_service + ai_prompts)
10. `image_pool_service.py` (依赖 wa_send + nas_upload + message_parser + reference_number)

---

## 阶段四：后端 API Blueprint 迁移

### 源文件 → 目标文件映射

所有 Blueprint 放到 `backend/app/api/`。

| # | wa-bot API 路由文件 | 行数 | 新建 Flask Blueprint | URL 前缀 |
|---|-------------------|------|---------------------|----------|
| 1 | `src/app/api/whatsapp/inbound/route.ts` | 587 | `wa_inbound.py` (`wa_inbound_bp`) | `/api/wa/inbound` |
| 2 | `src/app/api/whatsapp/outbound/route.ts` | 29 | `wa_outbound.py` (`wa_outbound_bp`) | `/api/wa/outbound` |
| 3 | `src/app/api/image-pool/*.ts` (4 files) | 182 | `wa_image_pool.py` (`wa_image_pool_bp`) | `/api/wa/image-pool` |
| 4 | `src/app/api/projects/*.ts` (3 files) | 116 | `wa_projects.py` (`wa_projects_bp`) | `/api/wa/projects` |
| 5 | `src/app/api/records/*.ts` (4 files) | 206 | `wa_records.py` (`wa_records_bp`) | `/api/wa/records` |
| 6 | `src/app/api/admin/*.ts` (6 files) | 229 | `wa_admin.py` (`wa_admin_bp`) | `/api/wa/admin` |
| 7 | `src/app/api/search/route.ts` + `dashboard/stats/route.ts` | 104 | `wa_dashboard.py` (`wa_dashboard_bp`) | `/api/wa` |
| 8 | `src/app/api/uploads/[...path]/route.ts` | 52 | `wa_uploads.py` (`wa_uploads_bp`) | `/api/wa/uploads` |

### Blueprint 注册（追加到 __init__.py）

```python
from app.api.wa_inbound import wa_inbound_bp
from app.api.wa_outbound import wa_outbound_bp
from app.api.wa_image_pool import wa_image_pool_bp
from app.api.wa_projects import wa_projects_bp
from app.api.wa_records import wa_records_bp
from app.api.wa_admin import wa_admin_bp
from app.api.wa_dashboard import wa_dashboard_bp
from app.api.wa_uploads import wa_uploads_bp

app.register_blueprint(wa_inbound_bp, url_prefix='/api/wa')
app.register_blueprint(wa_outbound_bp, url_prefix='/api/wa')
app.register_blueprint(wa_image_pool_bp, url_prefix='/api/wa/image-pool')
app.register_blueprint(wa_projects_bp, url_prefix='/api/wa/projects')
app.register_blueprint(wa_records_bp, url_prefix='/api/wa/records')
app.register_blueprint(wa_admin_bp, url_prefix='/api/wa/admin')
app.register_blueprint(wa_dashboard_bp, url_prefix='/api/wa')
app.register_blueprint(wa_uploads_bp, url_prefix='/api/wa/uploads')
```

### 实现顺序（按依赖）

1. `wa_uploads.py` (简单文件服务)
2. `wa_dashboard.py` (仅读 MongoDB)
3. `wa_projects.py` (CRUD)
4. `wa_records.py` (CRUD + wa_send_service)
5. `wa_image_pool.py` (依赖 image_pool_service)
6. `wa_admin.py` (CRUD + wa_send_service)
7. `wa_outbound.py` (依赖 wa_send_service)
8. `wa_inbound.py` (最复杂，依赖所有服务)

---

## 阶段五：Gateway 进程迁移

### 源文件 → 目标文件映射

Gateway 作为独立 Python 进程，放到 `backend/gateway/`。

| # | wa-bot 源文件 | 行数 | 新建 Python 文件 | 功能 |
|---|--------------|------|-----------------|------|
| 1 | `src/gateway/wakka-client.ts` | 212 | `gateway/wakka_client.py` | python-socketio 客户端连接 Wakka |
| 2 | `src/gateway/media-handler.ts` | 181 | `gateway/media_handler.py` | 下载/保存 WhatsApp 媒体文件 |
| 3 | `src/gateway/group-reminder.ts` | 315 | `gateway/group_reminder.py` | 群组未归类图片定时提醒 + Pillow 合成缩略图 |
| 4 | `src/gateway/index.ts` | 163 | `gateway/main.py` | 入口：消息监听、去重(LRU)、媒体处理、转发到 Flask |

### 实现顺序

1. `gateway/wakka_client.py`
2. `gateway/media_handler.py`
3. `gateway/group_reminder.py`
4. `gateway/main.py`

### 启动方式

```bash
# 开发
python gateway/main.py

# 生产 (docker-compose 中作为独立服务)
command: python gateway/main.py
```

---

## 阶段六：前端页面迁移

### 源文件 → 目标文件映射

所有新页面放到 `frontend/src/pages/wa/`，组件放到 `frontend/src/components/wa/`。

### 6.1 新增 Store

| # | 新建文件 | 功能 |
|---|---------|------|
| 1 | `frontend/src/store/waStore.ts` | WA 相关状态：项目、记录、图片池、搜索、Dashboard stats |

### 6.2 新增组件

| # | wa-bot 组件 | 行数 | 新建 React 文件 | 功能 |
|---|------------|------|----------------|------|
| 1 | `src/components/metric-card.tsx` | 59 | `components/wa/MetricCard.tsx` | Dashboard 指标卡 |
| 2 | `src/components/status-badge.tsx` | 72 | `components/wa/StatusBadge.tsx` | 记录/项目状态徽章 |
| 3 | `src/components/confidence-badge.tsx` | 21 | `components/wa/ConfidenceBadge.tsx` | AI 置信度徽章 |
| 4 | `src/components/record-table.tsx` | 195 | `components/wa/RecordTable.tsx` | 记录表格 |
| 5 | `src/components/record-detail-drawer.tsx` | 429 | `components/wa/RecordDetailDrawer.tsx` | 记录详情侧栏 |

### 6.3 新增页面

| # | wa-bot 页面 | 行数 | 新建 React 文件 | 路由 |
|---|------------|------|----------------|------|
| 1 | `(console)/page.tsx` | 148 | `pages/wa/WaDashboardPage.tsx` | `/wa` |
| 2 | `(console)/projects/page.tsx` | 113 | `pages/wa/WaProjectsPage.tsx` | `/wa/projects` |
| 3 | `(console)/projects/[id]/page.tsx` | 62 | `pages/wa/WaProjectDetailPage.tsx` | `/wa/projects/:id` |
| 4 | `(console)/image-pool/page.tsx` | 507 | `pages/wa/WaImagePoolPage.tsx` | `/wa/image-pool` |
| 5 | `(console)/search/page.tsx` | 84 | `pages/wa/WaSearchPage.tsx` | `/wa/search` |
| 6 | `(console)/admin/keywords/page.tsx` | 171 | `pages/wa/WaKeywordsPage.tsx` | `/wa/admin/keywords` |
| 7 | `(console)/admin/templates/page.tsx` | 206 | `pages/wa/WaTemplatesPage.tsx` | `/wa/admin/templates` |
| 8 | `(console)/admin/system/page.tsx` | 213 | `pages/wa/WaSystemPage.tsx` | `/wa/admin/system` |
| 9 | `(console)/admin/users/page.tsx` | 168 | (复用 v3 已有 AdminPage) | `/admin` |
| 10 | `(console)/admin/projects/page.tsx` | 153 | `pages/wa/WaManageProjectsPage.tsx` | `/wa/admin/projects` |

### 6.4 路由更新 (App.tsx)

```tsx
// 新增 WA 路由（在 Layout 内）
<Route path="wa" element={<WaDashboardPage />} />
<Route path="wa/projects" element={<WaProjectsPage />} />
<Route path="wa/projects/:id" element={<WaProjectDetailPage />} />
<Route path="wa/image-pool" element={<WaImagePoolPage />} />
<Route path="wa/search" element={<WaSearchPage />} />
<Route path="wa/admin/keywords" element={<WaKeywordsPage />} />
<Route path="wa/admin/templates" element={<WaTemplatesPage />} />
<Route path="wa/admin/system" element={<WaSystemPage />} />
<Route path="wa/admin/projects" element={<WaManageProjectsPage />} />
```

### 6.5 导航更新 (Layout.tsx)

替换当前的 "WA Bot" 外部跳转按钮为下拉子菜单：

```
WA Bot ▾
  ├── Dashboard
  ├── Projects
  ├── Image Pool
  ├── Search
  └── Admin ▸ (Keywords / Templates / System / Projects)
```

---

## 阶段七：认证统一

### 修改清单

| # | 文件 | 操作 |
|---|------|------|
| 1 | `backend/app/api/auth.py` | 移除 `wa-bot-token` 端点 |
| 2 | `backend/config.py` | 移除 `AUTO_LOGIN_SECRET`, `WA_BOT_URL`；新增 `WAKKA_*`, `NAS_*`, `MINI_*`, `OLLAMA_*` |
| 3 | `frontend/src/components/Layout.tsx` | 移除 `handleOpenWaBot` + auto-login 逻辑 |
| 4 | 所有新 WA API Blueprint | 使用 `@jwt_required()` + v3 角色权限 |

### 角色映射

| v3 角色 | WA 功能权限 |
|---------|-----------|
| `admin` | 全部 WA 功能 |
| `manager` | 项目/记录/图片池/搜索 |
| `user` | 仅查看自己关联的项目 |

---

## 阶段八：部署更新

### 8.1 环境变量（新增）

```env
# Wakka WhatsApp API
WAKKA_API_URL=https://wakka.prod.wellplay.io
WAKKA_API_KEY=wak_xxx

# Gateway
GATEWAY_INBOUND_SECRET=your-gateway-secret

# Ollama AI
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_TEXT_MODEL=gemma3:4b
OLLAMA_VISION_MODEL=llava:latest

# NAS (SFTP)
NAS_HOST=220.246.21.241
NAS_PORT=22
NAS_USER=aiuser
NAS_PASSWORD=xxx
NAS_BASE_DIR=/Project Photo for Installation
NAS_ENABLED=true

# Mac Mini (SSH/SCP)
MINI_HOST=100.81.190.62
MINI_USER=HaymondHo
MINI_SSH_KEY=~/.ssh/id_ed25519
MINI_DEST_DIR=~/Desktop/whats app
MINI_ENABLED=false
MINI_TARGET_GROUP_ID=xxx@g.us
```

### 8.2 Dockerfile 更新

```dockerfile
# 追加到现有 Dockerfile
RUN pip install --no-cache-dir python-socketio[client] paramiko scp requests

# 创建 WA 媒体目录
RUN mkdir -p uploads/wa-media
```

### 8.3 docker-compose.yml 更新

```yaml
# 新增 gateway 服务
gateway:
  build:
    context: ./backend
    dockerfile: Dockerfile
  environment:
    - WAKKA_API_URL=${WAKKA_API_URL}
    - WAKKA_API_KEY=${WAKKA_API_KEY}
    - GATEWAY_INBOUND_SECRET=${GATEWAY_INBOUND_SECRET}
    - FLASK_APP_URL=http://backend:8000
  volumes:
    - uploads_data:/app/uploads
  depends_on:
    - backend
  command: python gateway/main.py
  restart: unless-stopped
```

### 8.4 Vite proxy 更新 (vite.config.ts)

```typescript
// /api/wa 已被 /api 规则覆盖，无需额外配置
```

### 8.5 GitHub Pages 部署

无需修改 `.github/workflows/deploy-frontend.yml`，新页面自动包含在 `frontend/dist` 中。

---

## 阶段九：数据迁移

### 9.1 迁移脚本

创建 `backend/migrate_wa_data.py`：

```
功能：
1. 连接 wa-bot MongoDB (signhouse)
2. 读取 projects → 写入 v3 的 wa_projects
3. 读取 records → 写入 v3 的 wa_records
4. 读取 poolimages → 写入 v3 的 pool_images
5. 读取 grouppendingimages → 写入 v3 的 group_pending_images
6. 读取 keywords → 写入 v3 的 wa_keywords
7. 读取 recordtemplates → 写入 v3 的 wa_templates
8. 读取 organizations → 写入 v3 的 wa_organizations
9. 用户合并：按 email 匹配，不存在则创建
10. 复制 uploads/wa-media/ 文件
```

### 9.2 运行

```bash
cd backend
./venv/bin/python migrate_wa_data.py \
  --source mongodb://localhost:27017/signhouse \
  --target mongodb://localhost:27017/signhouse_dev
```

---

## 阶段十：清理

### 10.1 移除的文件/代码

| # | 操作 | 说明 |
|---|------|------|
| 1 | 移除 `backend/app/api/auth.py` 中的 `wa-bot-token` 端点 | 不再需要跨系统 SSO |
| 2 | 移除 `backend/config.py` 中的 `AUTO_LOGIN_SECRET`, `WA_BOT_URL` | 已内置 |
| 3 | 移除 `frontend/src/components/Layout.tsx` 中的 auto-login 相关代码 | 替换为内部路由 |
| 4 | 移除 `backend/.env` 中的 `AUTO_LOGIN_SECRET` | 已内置 |
| 5 | 更新 `.env.example` | 新增 WA 相关环境变量 |

### 10.2 验证清单

- [ ] v3 原有 OCR/标注功能正常
- [ ] WA Dashboard 显示统计
- [ ] WA 项目 CRUD 正常
- [ ] WA 记录查看/编辑/确认/作废正常
- [ ] 图片池浏览/分配/重试/删除正常
- [ ] 搜索功能正常
- [ ] Admin 关键词/模板/系统状态正常
- [ ] Gateway 连接 Wakka 并接收消息
- [ ] 私聊图片进入图片池
- [ ] 群聊图片归类正常
- [ ] NAS SFTP 上传正常
- [ ] Mac Mini SCP 传输正常
- [ ] AI 提取正常
- [ ] 自动跟进正常
- [ ] 角色权限控制正常

---

## 完整文件清单（按实现顺序）

### 后端新增文件（共 22 个）

```
backend/app/models/__init__.py          # [修改] 追加 WA 模型 helper
backend/app/__init__.py                 # [修改] 注册新 Blueprint + 索引
backend/config.py                       # [修改] 新增 WA 环境变量
backend/requirements.txt                # [修改] 追加依赖

backend/app/services/ai_prompts.py              # [新建] 1
backend/app/services/reference_number_service.py # [新建] 2
backend/app/services/message_parser_service.py   # [新建] 3
backend/app/services/wa_send_service.py          # [新建] 4
backend/app/services/nas_upload_service.py       # [新建] 5
backend/app/services/mini_transfer_service.py    # [新建] 6
backend/app/services/ai_extract_service.py       # [新建] 7
backend/app/services/extraction_runner_service.py # [新建] 8
backend/app/services/followup_service.py         # [新建] 9
backend/app/services/image_pool_service.py       # [新建] 10

backend/app/api/wa_uploads.py           # [新建] 11
backend/app/api/wa_dashboard.py         # [新建] 12
backend/app/api/wa_projects.py          # [新建] 13
backend/app/api/wa_records.py           # [新建] 14
backend/app/api/wa_image_pool.py        # [新建] 15
backend/app/api/wa_admin.py             # [新建] 16
backend/app/api/wa_outbound.py          # [新建] 17
backend/app/api/wa_inbound.py           # [新建] 18

backend/gateway/main.py                 # [新建] 19
backend/gateway/wakka_client.py         # [新建] 20
backend/gateway/media_handler.py        # [新建] 21
backend/gateway/group_reminder.py       # [新建] 22
```

### 前端新增文件（共 17 个）

```
frontend/src/store/waStore.ts                    # [新建] 1

frontend/src/components/wa/MetricCard.tsx         # [新建] 2
frontend/src/components/wa/StatusBadge.tsx        # [新建] 3
frontend/src/components/wa/ConfidenceBadge.tsx    # [新建] 4
frontend/src/components/wa/RecordTable.tsx        # [新建] 5
frontend/src/components/wa/RecordDetailDrawer.tsx # [新建] 6

frontend/src/pages/wa/WaDashboardPage.tsx         # [新建] 7
frontend/src/pages/wa/WaProjectsPage.tsx          # [新建] 8
frontend/src/pages/wa/WaProjectDetailPage.tsx     # [新建] 9
frontend/src/pages/wa/WaImagePoolPage.tsx         # [新建] 10
frontend/src/pages/wa/WaSearchPage.tsx            # [新建] 11
frontend/src/pages/wa/WaKeywordsPage.tsx          # [新建] 12
frontend/src/pages/wa/WaTemplatesPage.tsx         # [新建] 13
frontend/src/pages/wa/WaSystemPage.tsx            # [新建] 14
frontend/src/pages/wa/WaManageProjectsPage.tsx    # [新建] 15

frontend/src/App.tsx                              # [修改] 16 - 添加 WA 路由
frontend/src/components/Layout.tsx                # [修改] 17 - 更新导航
```

### 部署/配置文件（共 5 个）

```
backend/Dockerfile                      # [修改]
backend/.env                            # [修改]
docker-compose.yml                      # [修改]
backend/migrate_wa_data.py              # [新建] 数据迁移脚本
MIGRATION_GUIDE.md                      # [本文件]
```

### 总计：新建 39 个文件，修改 8 个文件
