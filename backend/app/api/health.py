"""Health check endpoints for monitoring and orchestration."""
from flask import Blueprint, jsonify
from app import mongo

health_bp = Blueprint('health', __name__)


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

