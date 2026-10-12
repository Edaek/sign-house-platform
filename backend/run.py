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


def _log_wa_mcp_endpoint(port: int) -> None:
    from werkzeug.middleware.dispatcher import DispatcherMiddleware

    if isinstance(app.wsgi_app, DispatcherMiddleware):
        print(f"WhatsApp MCP (HTTP): http://127.0.0.1:{port}/api/mcp/wa/mcp")
        print(f"WhatsApp MCP (SSE, dev only): http://127.0.0.1:{port}/api/mcp/wa/sse")
    else:
        print(
            "WhatsApp MCP (SSE): NOT mounted — pip install -r requirements.txt (a2wsgi) and restart",
            file=sys.stderr,
        )
        print("Diagnostics: GET /api/mcp/hosted-wa/status", file=sys.stderr)


def run_backend():
    host = app.config.get('HOST', '0.0.0.0')
    port = app.config.get('PORT', 5000)
    debug = app.config.get('DEBUG', True)
    print(f"Starting server on http://{host}:{port}")
    _log_wa_mcp_endpoint(int(port))
    app.run(host=host, port=port, debug=debug)


def run_gateway():
    from gateway.main import main as gateway_main
    gateway_main()


def run_all():
    import threading
    host = app.config.get('HOST', '0.0.0.0')
    port = app.config.get('PORT', 5000)

    t = threading.Thread(target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False), daemon=True)
    t.start()
    print(f"Backend started on http://{host}:{port}")
    _log_wa_mcp_endpoint(int(port))

    os.environ.setdefault('APP_URL', f'http://localhost:{port}')
    try:
        run_gateway()
    except Exception as e:
        logging.error('Gateway exited (%s); Flask API keeps running on port %s', e, port)
        t.join()


if __name__ == '__main__':
    if '--gateway' in sys.argv:
        run_gateway()
    elif '--all' in sys.argv:
        run_all()
    else:
        run_backend()
