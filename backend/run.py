#!/usr/bin/env python3
"""Run Sign House (v3 + MCP) or Gateway.

Usage:
    python run.py              # Flask backend + /mcp HTTP
    python run.py --gateway    # Wakka Socket.IO bridge
    python run.py --all        # Backend + gateway
"""
import logging
import os
import sys

if sys.version_info < (3, 10):
    print(
        f'Sign House backend requires Python 3.10+ (this interpreter is {sys.version.split()[0]}).\n'
        'On Mac mini: rm -rf .venv && python3.12 -m venv .venv && source .venv/bin/activate\n'
        '  pip install -r requirements.txt && pip install mcp a2wsgi',
        file=sys.stderr,
    )
    raise SystemExit(1)

logging.basicConfig(level=logging.INFO)

if '--all' in sys.argv:
    os.environ['SIGNHOUSE_START_SCHEDULERS'] = '1'

from app import create_app

app = create_app(os.environ.get('FLASK_CONFIG', 'development'))


def _mcp_http_mounted() -> bool:
    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    wsgi = app.wsgi_app
    if isinstance(wsgi, DispatcherMiddleware):
        return True
    while hasattr(wsgi, 'app'):
        wsgi = wsgi.app
        if isinstance(wsgi, DispatcherMiddleware):
            return True
    return False


def _log_mcp_endpoint(port: int) -> None:
    prefix = os.environ.get('MCP_HTTP_MOUNT_PREFIX', '/mcp').rstrip('/') or '/mcp'
    if _mcp_http_mounted():
        print(f'WhatsApp MCP (HTTP): http://127.0.0.1:{port}{prefix}')
        print(f'WhatsApp MCP (SSE, dev only): http://127.0.0.1:{port}{prefix}/sse')
    else:
        print('WhatsApp MCP: NOT mounted — pip install a2wsgi', file=sys.stderr)


def run_backend():
    host = app.config.get('HOST', '0.0.0.0')
    port = int(app.config.get('PORT', 5002))
    debug = app.config.get('DEBUG', True)
    print(f'Starting Sign House on http://{host}:{port}')
    print(f'WA API (MCP tools): {app.config.get("SIGN_HOUSE_API_URL")}')
    _log_mcp_endpoint(port)
    app.run(host=host, port=port, debug=debug, threaded=True)


def run_gateway():
    from gateway.main import main as gateway_main

    gateway_main()


def _wa_gateway_enabled() -> bool:
    raw = os.environ.get('SIGNHOUSE_WA_GATEWAY', 'true').strip().lower()
    return raw not in ('0', 'false', 'no', 'off')


def run_all():
    import threading
    import time

    if not _wa_gateway_enabled():
        print(
            'SIGNHOUSE_WA_GATEWAY=false — WhatsApp inbound via Loom+Wakka; '
            'Gateway not started (API + /mcp only).',
            file=sys.stderr,
        )
        run_backend()
        return

    host = app.config.get('HOST', '0.0.0.0')
    port = int(app.config.get('PORT', 5002))

    t = threading.Thread(
        target=lambda: app.run(
            host=host, port=port, debug=False, use_reloader=False, threaded=True,
        ),
        daemon=True,
    )
    t.start()
    print(f'Backend started on http://{host}:{port}')
    _log_mcp_endpoint(port)

    os.environ.setdefault('APP_URL', f'http://localhost:{port}')
    time.sleep(0.8)
    while True:
        try:
            run_gateway()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logging.error(
                'Gateway exited (%s); retrying in 5s (Flask still on port %s)',
                e,
                port,
            )
            time.sleep(5)


if __name__ == '__main__':
    if '--gateway' in sys.argv:
        run_gateway()
    elif '--all' in sys.argv:
        run_all()
    else:
        run_backend()
