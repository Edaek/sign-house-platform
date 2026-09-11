"""Probe CPU/GPU availability for PaddleOCR inference."""

import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Any] = {'at': 0.0, 'data': None}
_PROBE_TTL = 60.0


def _get_config_value(key: str, default=None):
    try:
        from flask import current_app
        return current_app.config.get(key, default)
    except RuntimeError:
        return os.environ.get(key, default)


def _is_gpu_only_mode() -> bool:
    value = _get_config_value('PADDLE_GPU_ONLY', 'false')
    if isinstance(value, bool):
        return value
    return str(value).lower() == 'true'


def _get_config_default_device() -> str:
    if _is_gpu_only_mode():
        return _get_config_value('PADDLE_DEVICE', 'gpu:0') or 'gpu:0'
    return _get_config_value('PADDLE_DEVICE', 'cpu') or 'cpu'


def canonicalize_device(raw: Optional[str]) -> str:
    if not raw:
        return 'cpu'
    value = str(raw).strip().lower()
    if value in ('gpu', 'cuda'):
        return 'gpu:0'
    if value.startswith('gpu:'):
        return value
    return 'cpu'


def _gpu_device_names(count: int) -> list:
    names = []
    try:
        import paddle
        for i in range(count):
            try:
                names.append(paddle.device.cuda.get_device_properties(i).name)
            except Exception:
                names.append(f'GPU {i}')
    except Exception:
        names = [f'GPU {i}' for i in range(count)]
    return names


def probe_compute_devices(force: bool = False) -> Dict[str, Any]:
    """Return CPU/GPU availability and recommended Paddle device strings."""
    now = time.time()
    if not force and _CACHE['data'] is not None and now - _CACHE['at'] < _PROBE_TTL:
        return _CACHE['data']

    cpu = {'available': True}
    gpu: Dict[str, Any] = {
        'available': False,
        'count': 0,
        'names': [],
        'cuda_version': None,
        'error': None,
    }
    paddle_package = 'unknown'
    paddle_version = None

    try:
        import paddle
        paddle_version = paddle.__version__
        cuda_compiled = paddle.device.is_compiled_with_cuda()
        cuda_version = None
        try:
            cuda_version = paddle.version.cuda()
        except Exception:
            pass
        paddle_package = 'gpu' if cuda_compiled else 'cpu'

        if cuda_compiled:
            count = paddle.device.cuda.device_count()
            gpu['count'] = count
            gpu['cuda_version'] = cuda_version
            if count > 0:
                gpu['names'] = _gpu_device_names(count)
                try:
                    paddle.set_device('gpu:0')
                    tensor = paddle.to_tensor([1.0], dtype='float32')
                    _ = tensor.numpy()
                    gpu['available'] = True
                except Exception as exc:
                    gpu['error'] = str(exc)
            else:
                gpu['error'] = 'No CUDA devices detected'
        else:
            gpu['error'] = 'Paddle is not compiled with CUDA (CPU wheel installed)'
    except ImportError as exc:
        paddle_package = 'missing'
        gpu['error'] = f'Paddle not installed: {exc}'
    except Exception as exc:
        gpu['error'] = str(exc)

    gpu_only = _is_gpu_only_mode()
    if gpu_only:
        cpu = {
            'available': False,
            'error': 'GPU-only mode (PADDLE_GPU_ONLY=true); Paddle OCR must use GPU on this host',
        }
        recommended = ['gpu:0'] if gpu['available'] else []
    else:
        recommended = ['cpu']
        if gpu['available']:
            recommended.append('gpu:0')

    default_device = canonicalize_device(_get_config_default_device())
    if default_device not in recommended:
        if gpu['available']:
            default_device = 'gpu:0'
        elif not gpu_only:
            default_device = 'cpu'
        else:
            default_device = 'gpu:0'

    result = {
        'cpu': cpu,
        'gpu': gpu,
        'gpu_only': gpu_only,
        'paddle_package': paddle_package,
        'paddle_version': paddle_version,
        'default_device': default_device,
        'recommended': recommended,
    }
    _CACHE['at'] = now
    _CACHE['data'] = result
    return result


def normalize_device(requested: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Resolve requested device to an available Paddle device string."""
    probe = probe_compute_devices()
    gpu_only = probe.get('gpu_only', False)
    recommended = probe.get('recommended', ['cpu'])

    if gpu_only:
        if probe.get('gpu', {}).get('available'):
            if requested and canonicalize_device(requested) != 'gpu:0':
                logger.warning('GPU-only host: ignoring device=%s, using gpu:0', requested)
            return 'gpu:0', None
        logger.error('GPU-only mode but no GPU available')
        return 'gpu:0', 'GPU required but not available on this host'

    target = canonicalize_device(requested or probe['default_device'])
    if target in recommended:
        return target, None
    fallback = probe.get('default_device', 'cpu')
    if fallback not in recommended:
        fallback = 'gpu:0' if probe.get('gpu', {}).get('available') else 'cpu'
    logger.warning('Requested Paddle device %s unavailable; using %s', target, fallback)
    return fallback, f'Device {target} unavailable, using {fallback}'
