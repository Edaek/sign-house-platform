import os
from flask import Flask
from flask_pymongo import PyMongo
from flask_jwt_extended import JWTManager
from flask_cors import CORS

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
    
    # Initialize extensions
    mongo.init_app(app)
    jwt.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
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
    
    # Register blueprints
    from app.api.auth import auth_bp
    from app.api.projects import projects_bp
    from app.api.processing import processing_bp
    from app.api.export import export_bp
    from app.api.admin import admin_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(projects_bp, url_prefix='/api/projects')
    app.register_blueprint(processing_bp, url_prefix='/api/processing')
    app.register_blueprint(export_bp, url_prefix='/api/export')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    
    return app
