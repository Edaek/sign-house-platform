# GPU Setup (Bare Metal)

> **完整中文指南**：请参阅 [GPU_LOCAL_GUIDE.md](GPU_LOCAL_GUIDE.md)（安装、配置、界面、API、排错、性能对比）。

Sign House uses **PaddleOCR** for text recognition. Shape detection (OpenCV) always runs on CPU; enabling GPU accelerates OCR only.

## HPE deployment (NVIDIA L20, GPU-only)

Target hardware confirmed on the HPE host:

| Item | Value |
|------|--------|
| GPU | 2 × NVIDIA L20 |
| Driver | 610.x |
| Host CUDA | 13.3 (driver report) |

On this machine **Paddle OCR cannot run on CPU** (CPU wheel / inference is incompatible). Use **GPU-only** mode:

### 1. Install dependencies (GPU Paddle)

From `backend/` with venv activated:

```bash
pip install -r requirements.txt
pip uninstall -y paddlepaddle
pip install -r requirements-gpu.txt
```

`requirements-gpu.txt` uses the **CUDA 12.6** Paddle wheel (`cu126`). The driver bundles a newer CUDA (13.3) but remains backward-compatible with the cu126 runtime inside the wheel. If import fails, try the cu118 index documented below.

### 2. Configure `.env` (required on HPE)

```env
PADDLE_DEVICE=gpu:0
PADDLE_GPU_ONLY=true
```

- `PADDLE_DEVICE=gpu:0` — default OCR device (first L20)
- `PADDLE_GPU_ONLY=true` — UI hides CPU, backend always uses GPU; prevents accidental CPU jobs

### 3. Verify

```bash
nvidia-smi
python -c "import paddle; print('cuda', paddle.device.is_compiled_with_cuda(), 'count', paddle.device.cuda.device_count())"
curl http://localhost:5001/api/health/compute-devices
```

Expected on HPE:

```json
{
  "gpu_only": true,
  "paddle_package": "gpu",
  "gpu": { "available": true, "count": 2, "names": ["NVIDIA L20", "..."] },
  "default_device": "gpu:0",
  "recommended": ["gpu:0"],
  "cpu": { "available": false, "error": "GPU-only mode ..." }
}
```

### 4. Second GPU (optional)

Jobs currently use `gpu:0` (first L20). Using `gpu:1` for a second worker would require a separate process bound to that device; default single-process `python run.py` uses one GPU.

---

## General GPU setup (other hosts)

### Prerequisites

1. NVIDIA driver installed (`nvidia-smi` works)
2. CUDA runtime compatible with the Paddle wheel (see [Paddle install docs](https://www.paddlepaddle.org.cn/install/quick))
3. Python 3.11 venv

### Install

```bash
pip install -r requirements.txt
pip uninstall -y paddlepaddle
pip install -r requirements-gpu.txt
```

Alternative CUDA index if cu126 fails:

```bash
pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
```

### Configure

```env
# GPU available, CPU still allowed (dev / comparison machines)
PADDLE_DEVICE=gpu:0

# Force GPU-only (HPE-style hosts)
# PADDLE_GPU_ONLY=true
```

## Performance comparison checklist

Use the **same** settings on both machines when comparing:

- Detection mode: Accurate
- Marker colors: identical
- Device: GPU (`PADDLE_DEVICE=gpu:0`, UI = GPU)
- Same PDF set

Record per-floorplan **Recognition time** and snapshot `/api/diagnostics`.

## Notes

- Run **one backend process** on GPU hosts (`python run.py`). Multiple Gunicorn workers multiply VRAM use.
- Dev machines without GPU keep `requirements.txt` + `PADDLE_DEVICE=cpu`; UI disables GPU when unavailable.
