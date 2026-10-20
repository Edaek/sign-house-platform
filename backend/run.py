#!/usr/bin/env python3
"""Run the Flask application or Gateway process.

Usage:
    python run.py              # Start Flask backend
    python run.py --gateway    # Start Gateway (Wakka Socket.IO bridge)
    python run.py --all        # Start both backend and gateway
"""
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)

# run.py --all uses debug=False + no reloader; schedulers must still start (see create_app).
if '--all' in sys.argv:
    os.environ['SIGNHOUSE_START_SCHEDULERS'] = '1'

from app import create_app

app = create_app(os.environ.get('FLASK_CONFIG', 'development'))

_MCP_PORT = 5010


def _assert_main_app_port(port: int) -> None:
    if port == _MCP_PORT:
        print(
            f'ERROR: PORT={port} is reserved for sign-house-mcp. Use PORT=5002 (or 5000) in backend/.env.',
            file=sys.stderr,
        )
        sys.exit(1)


def run_backend():
    host = app.config.get('HOST', '0.0.0.0')
    port = app.config.get('PORT', 5000)
    _assert_main_app_port(int(port))
    debug = app.config.get('DEBUG', True)
    print(f"Starting server on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)


def run_gateway():
    from gateway.main import main as gateway_main
    gateway_main()


def run_all():
    import threading
    host = app.config.get('HOST', '0.0.0.0')
    port = app.config.get('PORT', 5000)
    _assert_main_app_port(int(port))

    t = threading.Thread(target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False), daemon=True)
    t.start()
    print(f"Backend started on http://{host}:{port}")

    os.environ.setdefault('APP_URL', f'http://localhost:{port}')
    try:
        run_gateway()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        logging.error(
            'Gateway exited (code %s); Flask API keeps running on port %s',
            code,
            port,
        )
        if code != 0:
            while t.is_alive():
                t.join(timeout=86400)
    except Exception as e:
        logging.error('Gateway exited (%s); Flask API keeps running on port %s', e, port)
        while t.is_alive():
            t.join(timeout=86400)


if __name__ == '__main__':
    if '--gateway' in sys.argv:
        run_gateway()
    elif '--all' in sys.argv:
        run_all()
    else:
        run_backend()
