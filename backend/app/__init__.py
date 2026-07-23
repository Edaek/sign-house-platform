import os
from flask import Flask
from flask_pymongo import PyMongo
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flasgger import Swagger

from config import config

mongo = PyMongo()
jwt = JWTManager()


def create_app(config_name=None):
    """Application factory."""
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'development')
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'templates'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'images'), exist_ok=True)
    os.makedirs(app.config['SHAPE_TEMPLATES_FOLDER'], exist_ok=True)
    
    # Initialize extensions
    mongo.init_app(app)
    jwt.init_app(app)
    
    # Configure CORS with dynamic origins from config
    allowed_origins = app.config.get('ALLOWED_ORIGINS', ['*'])
    CORS(app, 
         resources={r"/api/*": {
             "origins": allowed_origins,
             "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
             "allow_headers": ["Content-Type", "Authorization"],
             "supports_credentials": True
         }})
    
    # Configure Swagger/OpenAPI documentation
    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": 'apispec',
                "route": '/apispec.json',
                "rule_filter": lambda rule: True,
                "model_filter": lambda tag: True,
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/api-docs/"
    }
    
    swagger_template = {
        "info": {
            "title": "Sign House API",
            "description": "API for Sign House - OCR and floorplan processing system",
            "version": "3.0.0",
            "contact": {
                "name": "Sign House",
            }
        },
        "securityDefinitions": {
            "Bearer": {
                "type": "apiKey",
                "name": "Authorization",
                "in": "header",
                "description": "JWT Authorization header using the Bearer scheme. Example: 'Authorization: Bearer {token}'"
            }
        },
        "security": [{"Bearer": []}]
    }
    
    Swagger(app, config=swagger_config, template=swagger_template)
    
    # Create indexes
    with app.app_context():
        # Users indexes
        mongo.db.users.create_index('username', unique=True)
        mongo.db.users.create_index('email', unique=True)
        mongo.db.users.create_index('role')
        # Projects indexes
        mongo.db.projects.create_index('user_id')
        # Floorplans indexes
        mongo.db.floorplans.create_index('project_id')
        # Extracted data indexes
        mongo.db.extracted_data.create_index('floorplan_id')
        # Audit logs indexes
        mongo.db.audit_logs.create_index('user_id')
        mongo.db.audit_logs.create_index('timestamp')
        mongo.db.audit_logs.create_index([('user_id', 1), ('timestamp', -1)])
        # Project members indexes
        mongo.db.project_members.create_index([('project_id', 1), ('user_id', 1)], unique=True)
        mongo.db.project_members.create_index('user_id')
        mongo.db.project_members.create_index('project_id')
        # Dictionary indexes
        mongo.db.dictionary.create_index('english')
        mongo.db.dictionary.create_index('chinese')
        # Processing jobs indexes
        mongo.db.processing_jobs.create_index('job_id', unique=True)
        mongo.db.processing_jobs.create_index('project_id')
        mongo.db.processing_jobs.create_index([('project_id', 1), ('created_at', -1)])
        # Shape templates indexes (self-learning)
        mongo.db.shape_templates.create_index('shape_type')
        mongo.db.shape_templates.create_index('is_active')
    
    # Register blueprints
    from app.api.health import health_bp
    from app.api.auth import auth_bp
    from app.api.projects import projects_bp
    from app.api.processing import processing_bp
    from app.api.export import export_bp
    from app.api.admin import admin_bp
    from app.api.dictionary import dictionary_bp
    from app.api.watcher import watcher_bp
    
    app.register_blueprint(health_bp)  # No prefix - health checks at root level
    app.register_blueprint(health_bp, url_prefix='/api', name='health_api')
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(projects_bp, url_prefix='/api/projects')
    app.register_blueprint(processing_bp, url_prefix='/api/processing')
    app.register_blueprint(export_bp, url_prefix='/api/export')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(dictionary_bp, url_prefix='/api/dictionary')
    app.register_blueprint(watcher_bp, url_prefix='/api/watcher')
    
    # Initialize folder watcher manager with app context
    from app.services.folder_watcher import watcher_manager
    watcher_manager.init_app(app)
    
    return app
