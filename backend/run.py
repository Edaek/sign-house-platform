#!/usr/bin/env python3
"""Run the Flask application."""
import os
from app import create_app

app = create_app(os.environ.get('FLASK_CONFIG', 'development'))


if __name__ == '__main__':
    host = app.config.get('HOST', '0.0.0.0')
    port = app.config.get('PORT', 5000)
    debug = app.config.get('DEBUG', True)
    
    print(f"Starting server on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
