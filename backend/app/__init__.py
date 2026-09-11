import json
import os
from datetime import datetime

from flask import Flask
from flask_pymongo import PyMongo
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flasgger import Swagger
from bson import ObjectId

from config import config

mongo = PyMongo()
jwt = JWTManager()


def _sync_bundled_shape_templates(app):
    """Insert git-bundled learned templates that this Mongo DB does not have yet."""
    folder = app.config['SHAPE_TEMPLATES_FOLDER']
    seed_path = os.path.join(folder, 'seed.json')
    if not os.path.isfile(seed_path):
        return
    with open(seed_path, encoding='utf-8') as f:
        items = json.load(f)
    for item in items:
        tid = ObjectId(item['_id'])
        png = os.path.join(folder, f'{item["_id"]}.png')
        if not os.path.isfile(png):
            continue
        existing = mongo.db.shape_templates.find_one({'_id': tid})
        if existing:
            if existing.get('image_path') != png:
                mongo.db.shape_templates.update_one(
                    {'_id': tid}, {'$set': {'image_path': png}})
            continue
        mongo.db.shape_templates.insert_one({
            '_id': tid,
            'shape_type': item.get('shape_type', 'circle'),
            'image_path': png,
            'width': item.get('width', 0),
            'height': item.get('height', 0),
            'color_profile': item.get('color_profile'),
            'extracted_text': item.get('extracted_text') or '',
            'is_active': item.get('is_active', True),
            'match_count': 0,
            'created_at': datetime.utcnow(),
        })


def create_app(config_name=None):
    """Application factory."""
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'development')
    
    app = Flask(__name__)
    app.url_map.strict_slashes = False
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
        _sync_bundled_shape_templates(app)

        # WA collections indexes
        mongo.db.wa_records.create_index('referenceNumber', unique=True)
        mongo.db.wa_records.create_index([('projectId', 1), ('status', 1)])
        mongo.db.wa_records.create_index([('createdAt', -1)])
        mongo.db.wa_records.create_index([('senderPhone', 1), ('status', 1), ('createdAt', -1)])
        mongo.db.wa_projects.create_index('code', unique=True)
        mongo.db.wa_projects.create_index('status')
        mongo.db.pool_images.create_index([('phone', 1), ('projectId', 1)])
        mongo.db.pool_images.create_index([('createdAt', -1)])
        mongo.db.group_pending_images.create_index([('groupId', 1), ('categorized', 1)])
        mongo.db.group_pending_images.create_index('batchId')
        mongo.db.wa_keywords.create_index([('term', 1), ('projectId', 1)])
        mongo.db.wa_keywords.create_index('type')
        mongo.db.wa_templates.create_index([('projectId', 1), ('typeName', 1)])
        mongo.db.wa_pending_photos.create_index('createdAt', expireAfterSeconds=3600)
        mongo.db.pool_images.create_index(
            'assignedAt', expireAfterSeconds=30 * 86400,
            partialFilterExpression={'assignedAt': {'$exists': True}},
        )
        mongo.db.group_pending_images.create_index('botReminderMsgIds')
        mongo.db.wa_records.create_index([
            ('referenceNumber', 'text'),
            ('rawMessage', 'text'),
            ('senderName', 'text'),
            ('senderPhone', 'text'),
        ], name='wa_records_text')
    
    # Ensure WA uploads folder exists
    os.makedirs(app.config.get('WA_UPLOADS_FOLDER', os.path.join(app.config['UPLOAD_FOLDER'], 'wa-media')), exist_ok=True)
    
    # Register blueprints
    from app.api.health import health_bp
    from app.api.auth import auth_bp
    from app.api.projects import projects_bp
    from app.api.processing import processing_bp
    from app.api.export import export_bp
    from app.api.admin import admin_bp
    from app.api.dictionary import dictionary_bp
    from app.api.watcher import watcher_bp
    from app.api.wa_dashboard import wa_dashboard_bp
    from app.api.wa_projects import wa_projects_bp
    from app.api.wa_records import wa_records_bp
    from app.api.wa_image_pool import wa_image_pool_bp
    from app.api.wa_admin import wa_admin_bp
    from app.api.wa_uploads import wa_uploads_bp
    from app.api.wa_inbound import wa_inbound_bp
    from app.api.wa_outbound import wa_outbound_bp
    from app.api.wa_nas import wa_nas_bp
    
    app.register_blueprint(health_bp)  # No prefix - health checks at root level
    app.register_blueprint(health_bp, url_prefix='/api', name='health_api')
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(projects_bp, url_prefix='/api/projects')
    app.register_blueprint(processing_bp, url_prefix='/api/processing')
    app.register_blueprint(export_bp, url_prefix='/api/export')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(dictionary_bp, url_prefix='/api/dictionary')
    app.register_blueprint(watcher_bp, url_prefix='/api/watcher')
    app.register_blueprint(wa_dashboard_bp, url_prefix='/api/wa')
    app.register_blueprint(wa_projects_bp, url_prefix='/api/wa/projects')
    app.register_blueprint(wa_records_bp, url_prefix='/api/wa/records')
    app.register_blueprint(wa_image_pool_bp, url_prefix='/api/wa/image-pool')
    app.register_blueprint(wa_admin_bp, url_prefix='/api/wa/admin')
    app.register_blueprint(wa_uploads_bp, url_prefix='/api/wa/uploads')
    app.register_blueprint(wa_inbound_bp, url_prefix='/api/wa')
    app.register_blueprint(wa_outbound_bp, url_prefix='/api/wa')
    app.register_blueprint(wa_nas_bp, url_prefix='/api/wa/nas')
    
    # Initialize folder watcher manager with app context
    from app.services.folder_watcher import watcher_manager
    watcher_manager.init_app(app)

    # Initialize NAS local-mount service
    from app.services.nas_watcher_service import nas_mount
    nas_mount.init_app(app)

    # Recover zombie jobs from prior crashes, then watch for stale workers
    from app.services.job_recovery import recover_stale_jobs, start_stale_job_watchdog
    with app.app_context():
        try:
            recovered = recover_stale_jobs()
            if recovered:
                app.logger.info('Recovered %d stale job(s) on startup', recovered)
        except Exception:
            app.logger.exception('Startup stale job recovery failed')
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        start_stale_job_watchdog(app)
    
    return app
