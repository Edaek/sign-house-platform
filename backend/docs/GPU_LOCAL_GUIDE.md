# Sign House 本地 GPU 使用完整指南

本文说明如何在**裸机（bare metal）**环境下，于本地或 HPE 服务器启用 PaddleOCR 的 GPU 加速，并通过 Sign House 界面切换与验证设备。

---

## 1. 原理说明

Sign House 检测流水线分为两段：

| 阶段 | 技术栈 | 设备 |
|------|--------|------|
| 形状检测（圆/矩形） | OpenCV | **始终 CPU** |
| 文字识别 OCR | PaddleOCR | **可选 CPU 或 GPU** |

启用 GPU **只加速 OCR**，不改变形状检测逻辑。两台机器做性能对比时，应统一：

- `detection_mode`（Fast / Accurate）
- `marker_colors`
- **`paddle_device`（cpu 或 gpu:0）**
- 同一批 PDF

---

## 2. 环境要求

### 2.1 必须使用 NVIDIA GPU

- 需要 **NVIDIA 显卡** + 已安装驱动
- 终端可运行 `nvidia-smi` 并看到 GPU 信息
- **Apple Mac（M 系列 / Intel 无 NVIDIA）无法使用本指南的 GPU 方案**，只能 CPU

### 2.2 软件版本（与项目锁定一致）

| 组件 | 版本 |
|------|------|
| Python | 3.11+（推荐与项目 venv 一致） |
| paddlepaddle-gpu | 3.3.0 |
| paddleocr | 3.7.0 |
| MongoDB | 本地或远程实例 |

### 2.3 参考硬件：HPE 服务器

| 项目 | 配置 |
|------|------|
| GPU | 2 × NVIDIA L20 |
| 驱动 | 610.x |
| 驱动报告 CUDA | 13.3 |
| Paddle wheel | cu126（CUDA 12.6 运行时，与较新驱动向后兼容） |

> HPE 上 Paddle OCR **无法在 CPU 模式运行**，必须配置 GPU-only（见第 4 节）。

---

## 3. 安装步骤

### 3.1 克隆代码并进入后端目录

```bash
cd /path/to/sign-house-v3/backend
```

### 3.2 创建并激活虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate    # Linux
# 或 Windows: venv\Scripts\activate
```

### 3.3 安装基础依赖（含 paddleocr、opencv 等）

```bash
pip install -r requirements.txt
```

此时默认安装的是 **CPU 版** `paddlepaddle==3.3.0`。

### 3.4 替换为 GPU 版 Paddle

```bash
pip uninstall -y paddlepaddle
pip install -r requirements-gpu.txt
```

`requirements-gpu.txt` 默认从 Paddle 官方源安装 **CUDA 12.6（cu126）** 的 GPU 包。

**若 cu126 安装或 import 失败**，尝试 CUDA 11.8：

```bash
pip uninstall -y paddlepaddle paddlepaddle-gpu
pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
```

更多版本见 [Paddle 官方安装页](https://www.paddlepaddle.org.cn/install/quick)。

### 3.5 验证 Paddle GPU

```bash
nvidia-smi

python -c "
import paddle
print('Paddle version:', paddle.__version__)
print('CUDA compiled:', paddle.device.is_compiled_with_cuda())
print('GPU count:', paddle.device.cuda.device_count())
if paddle.device.cuda.device_count() > 0:
    paddle.set_device('gpu:0')
    t = paddle.to_tensor([1.0])
    print('GPU smoke test OK:', t.numpy())
"
```

期望输出：

- `CUDA compiled: True`
- `GPU count: >= 1`
- `GPU smoke test OK: [1.]`

---

## 4. 配置环境变量

复制并编辑 `backend/.env`（勿提交到 git）：

```bash
cp .env.example .env
```

### 4.1 通用 NVIDIA 本地机（CPU/GPU 均可）

适合开发机或需要 CPU/GPU 对比测试的服务器：

```env
# ── Paddle OCR device ───────────────────────────
PADDLE_DEVICE=gpu:0
```

- 默认 OCR 走第一块 GPU
- 首页 Dashboard 仍可在 CPU / GPU 间切换（若 CPU wheel 也保留则 CPU 可选；仅装 GPU 包时通常只有 GPU）

### 4.2 HPE 服务器（仅 GPU）

```env
PADDLE_DEVICE=gpu:0
PADDLE_GPU_ONLY=true
```

| 变量 | 作用 |
|------|------|
| `PADDLE_DEVICE=gpu:0` | 默认使用第一块 L20 |
| `PADDLE_GPU_ONLY=true` | 强制 GPU；UI 隐藏 CPU；后端拒绝 CPU 任务 |

### 4.3 其他常用配置

确保 MongoDB 等基础项已配置，例如：

```env
MONGO_URI=mongodb://localhost:27017/signhouse_v3
PORT=5001
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001
```

`PORT` 需与前端 `vite.config.ts` 中 proxy 目标一致（默认 `5001`）。

---

## 5. 启动服务

### 5.1 启动 MongoDB

确保 MongoDB 已运行且 `MONGO_URI` 可连接。

### 5.2 启动后端

```bash
cd backend
source venv/bin/activate
PORT=5001 python run.py
```

成功后可访问：`http://localhost:5001/health`

> **重要**：GPU 场景请保持 **单进程** `python run.py`。不要使用多 worker 的 Gunicorn，否则每个 worker 各加载一份模型，显存占用成倍增加。

### 5.3 启动前端

```bash
cd frontend
npm install   # 首次
npm run dev
```

浏览器打开：`http://localhost:3000` 或 `http://localhost:3001`（以实际端口为准）。

---

## 6. 界面操作（Dashboard）

设备管理集中在 **Projects 首页**（Dashboard），不在单个项目上传页重复显示。

1. 登录后进入 **Projects** 首页
2. 标题下方找到 **OCR Engine** 工具栏
3. 点击 **↻（刷新）** 按钮 — 重新检测 CPU/GPU 可用性
4. 在分段控件中选择 **GPU**（HPE `PADDLE_GPU_ONLY=true` 时仅显示 GPU）
5. 选择会保存到浏览器 `localStorage`，对所有新检测任务生效

### 6.1 面板信息说明

| 显示 | 含义 |
|------|------|
| `Paddle gpu 3.3.0` | 已安装 GPU 版 Paddle |
| `2 GPUs · NVIDIA L20` | 检测到 GPU 数量与型号 |
| `GPU only` | 已启用 `PADDLE_GPU_ONLY` |
| GPU 按钮灰色 | 未装 GPU 包、无显卡或 CUDA 不可用 |

---

## 7. API 验证

### 7.1 完整设备探测

```bash
curl -s http://localhost:5001/api/health/compute-devices | python3 -m json.tool
```

强制刷新缓存（跳过 60 秒 TTL）：

```bash
curl -s 'http://localhost:5001/api/health/compute-devices?force=1' | python3 -m json.tool
```

**GPU 就绪示例：**

```json
{
  "cpu": { "available": true },
  "gpu": {
    "available": true,
    "count": 2,
    "names": ["NVIDIA L20", "NVIDIA L20"],
    "cuda_version": "12.6",
    "error": null
  },
  "gpu_only": false,
  "paddle_package": "gpu",
  "paddle_version": "3.3.0",
  "default_device": "gpu:0",
  "recommended": ["cpu", "gpu:0"]
}
```

**HPE GPU-only 示例：**

```json
{
  "gpu_only": true,
  "default_device": "gpu:0",
  "recommended": ["gpu:0"],
  "cpu": {
    "available": false,
    "error": "GPU-only mode (PADDLE_GPU_ONLY=true); Paddle OCR must use GPU on this host"
  }
}
```

### 7.2 诊断摘要

```bash
curl -s http://localhost:5001/api/diagnostics | python3 -m json.tool
```

关注 `compute_devices` 字段，用于部署报告截图（含 commit、Paddle 版本）。

---

## 8. 运行检测任务

配置完成后，以下操作均会使用 Dashboard 所选设备（或 `.env` 默认值）：

| 操作 | 路径 |
|------|------|
| 批量上传 PDF | 项目页 → Upload |
| 恢复 pending 任务 | 项目页 → Resume |
| 单页 Detect | 编辑器页 |
| 文件夹 Watcher | 项目页 → Folder Watch |

批量进度弹窗会显示 `OCR: GPU` 或 `OCR: CPU`。

---

## 9. 性能对比流程（两台机器）

1. 两台机器使用 **相同 git commit**
2. `.env` 均设 `PADDLE_DEVICE=gpu:0`
3. Dashboard 均选 **GPU**，模式选 **Accurate**，marker colors 一致
4. 上传 **相同 PDF 集合**
5. 记录项目页每行 **Recognition time**
6. 分别截图 `/api/diagnostics` 中的 `compute_devices`

---

## 10. 常见问题

### Q1：Dashboard 上 GPU 按钮是灰色的

**原因：**

- 仍为 CPU 版 `paddlepaddle`（未执行第 3.4 步）
- 机器无 NVIDIA GPU（如 Mac）
- 驱动未装或 `nvidia-smi` 失败
- CUDA 版本与 wheel 不匹配

**处理：** 按第 3 节重装 GPU 包，并运行第 7 节 API 查看 `gpu.error` 具体原因。

---

### Q2：`Paddle is not compiled with CUDA (CPU wheel installed)`

说明当前 venv 里是 CPU 包：

```bash
pip uninstall -y paddlepaddle paddlepaddle-gpu
pip install -r requirements-gpu.txt
```

重启后端后再检测。

---

### Q3：改了 `.env` 不生效

修改 `PADDLE_DEVICE` / `PADDLE_GPU_ONLY` 后必须 **重启** `python run.py`。Flask debug 模式会自动重载代码，但部分配置仅在进程启动时读取。

---

### Q4：Mac 本地能否用 GPU？

不能。Mac 无 NVIDIA CUDA，请保持：

```env
PADDLE_DEVICE=cpu
```

并使用 `requirements.txt`（CPU 版 Paddle）。

---

### Q5：HPE 有两块 L20，会用哪块？

默认 **`gpu:0`**（第一块）。当前单后端进程只使用一块 GPU。要用第二块需单独部署进程并指定设备，本项目暂未内置 `gpu:1` UI 选项。

---

### Q6：显存不足 OOM

- 确保只运行 **一个** 后端进程
- 关闭其他占用 GPU 的程序
- 首次 OCR 会加载模型，占用数 GB 显存属正常

---

## 11. 快速命令清单

```bash
# 1. 安装 GPU Paddle
cd backend && source venv/bin/activate
pip install -r requirements.txt
pip uninstall -y paddlepaddle
pip install -r requirements-gpu.txt

# 2. 验证
nvidia-smi
python -c "import paddle; print(paddle.device.is_compiled_with_cuda(), paddle.device.cuda.device_count())"

# 3. 配置 .env
# PADDLE_DEVICE=gpu:0
# PADDLE_GPU_ONLY=true   # 仅 HPE

# 4. 启动
PORT=5001 python run.py

# 5. 检测 API
curl -s http://localhost:5001/api/health/compute-devices?force=1 | python3 -m json.tool
```

---

## 12. 相关文件

| 文件 | 说明 |
|------|------|
| [`requirements-gpu.txt`](../requirements-gpu.txt) | GPU 版 Paddle 安装 |
| [`backend/.env.example`](../.env.example) | 环境变量模板 |
| [`app/services/device_probe.py`](../app/services/device_probe.py) | 设备探测逻辑 |
| [`GPU_SETUP.md`](GPU_SETUP.md) | 简明部署备忘 |

---

## 13. 回退到 CPU

```bash
pip uninstall -y paddlepaddle-gpu
pip install paddlepaddle==3.3.0
```

`.env`：

```env
PADDLE_DEVICE=cpu
# 删除或注释 PADDLE_GPU_ONLY
```

重启后端，Dashboard 选择 CPU 即可。
