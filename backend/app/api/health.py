"""Health check endpoints for monitoring and orchestration."""
import subprocess
from flask import Blueprint, jsonify
from app import mongo

health_bp = Blueprint('health', __name__)


def _get_git_commit():
    """Get current git commit hash, or 'unknown' if not in a git repo."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else 'unknown'
    except Exception:
        return 'unknown'


@health_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint for monitoring
    ---
    tags:
      - Health
    responses:
      200:
        description: Service is healthy
        schema:
          type: object
          properties:
            status:
              type: string
              example: healthy
            database:
              type: string
              example: healthy
      503:
        description: Service is unhealthy
        schema:
          type: object
          properties:
            status:
              type: string
              example: unhealthy
            database:
              type: string
              example: unhealthy
            error:
              type: string
    """
    try:
        # Check MongoDB connection
        mongo.db.command('ping')
        db_status = 'healthy'
    except Exception as e:
        db_status = 'unhealthy'
        return jsonify({
            'status': 'unhealthy',
            'database': db_status,
            'error': str(e)
        }), 503
    
    return jsonify({
        'status': 'healthy',
        'database': db_status
    }), 200


@health_bp.route('/ready', methods=['GET'])
def readiness_check():
    """
    Readiness check for orchestration platforms
    ---
    tags:
      - Health
    responses:
      200:
        description: Service is ready to accept traffic
        schema:
          type: object
          properties:
            ready:
              type: boolean
              example: true
    """
    return jsonify({'ready': True}), 200


@health_bp.route('/live', methods=['GET'])
def liveness_check():
    """
    Liveness check for orchestration platforms
    ---
    tags:
      - Health
    responses:
      200:
        description: Service is alive
        schema:
          type: object
          properties:
            alive:
              type: boolean
              example: true
    """
    return jsonify({'alive': True}), 200


@health_bp.route('/diagnostics', methods=['GET'])
def diagnostics():
    """Diagnostics endpoint for verifying deployment status and dependencies."""
    info = {
        'commit': _get_git_commit(),
        'paddleocr': 'unknown',
        'opencv': 'unknown',
        'numpy': 'unknown',
    }

    try:
        import cv2
        info['opencv'] = cv2.__version__
    except Exception as e:
        info['opencv'] = f'error: {e}'

    try:
        import numpy as np
        info['numpy'] = np.__version__
    except Exception as e:
        info['numpy'] = f'error: {e}'

    try:
        from paddleocr import PaddleOCR
        info['paddleocr'] = 'available'
    except Exception as e:
        info['paddleocr'] = f'error: {e}'

    try:
        mongo.db.command('ping')
        info['database'] = 'healthy'
    except Exception as e:
        info['database'] = f'unhealthy: {e}'

    return jsonify(info), 200

