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
from app import create_app

logging.basicConfig(level=logging.INFO)

app = create_app(os.environ.get('FLASK_CONFIG', 'development'))


def run_backend():
    host = app.config.get('HOST', '0.0.0.0')
    port = app.config.get('PORT', 5000)
    debug = app.config.get('DEBUG', True)
    print(f"Starting server on http://{host}:{port}")
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

    os.environ.setdefault('APP_URL', f'http://localhost:{port}')
    run_gateway()


if __name__ == '__main__':
    if '--gateway' in sys.argv:
        run_gateway()
    elif '--all' in sys.argv:
        run_all()
    else:
        run_backend()
