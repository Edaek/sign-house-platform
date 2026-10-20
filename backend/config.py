import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Server Configuration
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 5000))
    
    # JWT Configuration
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
    
    # MongoDB Configuration
    MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/signhouse_dev')
    
    # File Upload Configuration
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    SHAPE_TEMPLATES_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'shape_templates')
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max for batch folder uploads
    ALLOWED_EXTENSIONS = {'pdf', 'xlsx', 'xls'}
    
    # Tesseract Configuration
    TESSERACT_CMD = os.environ.get('TESSERACT_CMD', '/usr/local/bin/tesseract')
    
    # PDF Processing Configuration
    PDF_DPI = int(os.environ.get('PDF_DPI', 200))
    PDF_PREVIEW_DPI = int(os.environ.get('PDF_PREVIEW_DPI', 150))
    
    # Title Block Extraction Configuration (for floor plan title extraction)
    TITLE_REGION_X_START = int(os.environ.get('TITLE_REGION_X_START', 60))  # 60% from left
    TITLE_REGION_Y_START = int(os.environ.get('TITLE_REGION_Y_START', 85))  # 85% from top
    TITLE_REGION_WIDTH = int(os.environ.get('TITLE_REGION_WIDTH', 40))      # 40% of image width
    TITLE_REGION_HEIGHT = int(os.environ.get('TITLE_REGION_HEIGHT', 15))    # 15% of image height
    
    # CORS Configuration
    ALLOWED_ORIGINS = [
        o.strip()
        for o in os.environ.get('ALLOWED_ORIGINS', 'http://localhost:3000').split(',')
        if o.strip()
    ]
    
    # Wakka WhatsApp API
    WAKKA_API_URL = os.environ.get('WAKKA_API_URL', '')
    WAKKA_API_KEY = os.environ.get('WAKKA_API_KEY', '')

    # Gateway
    GATEWAY_INBOUND_SECRET = os.environ.get('GATEWAY_INBOUND_SECRET', '')

    # Ollama AI
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
    OLLAMA_TEXT_MODEL = os.environ.get('OLLAMA_TEXT_MODEL', 'gemma3:4b')
    OLLAMA_VISION_MODEL = os.environ.get('OLLAMA_VISION_MODEL', 'llava:latest')

    # NAS (SFTP upload)
    NAS_HOST = os.environ.get('NAS_HOST', '')
    NAS_PORT = int(os.environ.get('NAS_PORT', 22))
    NAS_USER = os.environ.get('NAS_USER', '')
    NAS_PASSWORD = os.environ.get('NAS_PASSWORD', '')
    NAS_BASE_DIR = os.environ.get('NAS_BASE_DIR', '/Project Photo for Installation')
    NAS_ENABLED = os.environ.get('NAS_ENABLED', 'false').lower() == 'true'

    # NAS local mount (Mac Mini where NAS is mounted via SMB)
    NAS_WATCH_DIR = os.environ.get('NAS_WATCH_DIR', '/Volumes/Project Photo for Installation/Project Photo for Installation')
    NAS_SCAN_MAX_DEPTH = int(os.environ.get('NAS_SCAN_MAX_DEPTH', 6))
    # SMB: treat volume mounted as connected (avoid isdir/list timeouts marking "disconnected")
    NAS_FAST_CONNECT = os.environ.get('NAS_FAST_CONNECT', 'true').lower() == 'true'
    NAS_PROBE_TIMEOUT_S = float(os.environ.get('NAS_PROBE_TIMEOUT_S', 4))
    NAS_FOLDER_CACHE_TTL_S = int(os.environ.get('NAS_FOLDER_CACHE_TTL_S', 600))
    NAS_FOLDER_CACHE_REFRESH_S = int(os.environ.get('NAS_FOLDER_CACHE_REFRESH_S', 300))
    NAS_IO_TIMEOUT_S = float(os.environ.get('NAS_IO_TIMEOUT_S', 45))

    # Mac Mini (SSH/SCP)
    MINI_HOST = os.environ.get('MINI_HOST', '')
    MINI_USER = os.environ.get('MINI_USER', '')
    MINI_SSH_KEY = os.environ.get('MINI_SSH_KEY', '')
    MINI_DEST_DIR = os.environ.get('MINI_DEST_DIR', '~/Desktop/whats app')
    MINI_ENABLED = os.environ.get('MINI_ENABLED', 'false').lower() == 'true'
    MINI_LOCAL = os.environ.get('MINI_LOCAL', 'false').lower() == 'true'
    MINI_TARGET_GROUP_ID = os.environ.get('MINI_TARGET_GROUP_ID', '')

    # WA uploads folder (media from WhatsApp)
    WA_UPLOADS_FOLDER = os.environ.get(
        'WA_UPLOADS_FOLDER',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'wa-media'),
    )

    # Group periodic reminders for uncategorized images
    GROUP_REMINDER_ENABLED = os.environ.get('GROUP_REMINDER_ENABLED', 'true').lower() == 'true'
    GROUP_REMINDER_INTERVAL_MS = int(os.environ.get('GROUP_REMINDER_INTERVAL_MS', 40000))
    GROUP_REMINDER_COOLDOWN_S = int(os.environ.get('GROUP_REMINDER_COOLDOWN_S', '40'))
    GROUP_REMINDER_ATTACH_COMPOSITE = (
        os.environ.get('GROUP_REMINDER_ATTACH_COMPOSITE', 'false').lower() == 'true'
    )

    # Private-chat: poll Media Pool for unassigned images (like group @ reminders)
    POOL_REMINDER_ENABLED = os.environ.get('POOL_REMINDER_ENABLED', 'true').lower() == 'true'
    POOL_REMINDER_INTERVAL_MS = int(os.environ.get('POOL_REMINDER_INTERVAL_MS', '40000'))
    POOL_REMINDER_COOLDOWN_S = int(os.environ.get('POOL_REMINDER_COOLDOWN_S', '50'))
    POOL_REMINDER_BATCH_GRACE_S = int(os.environ.get('POOL_REMINDER_BATCH_GRACE_S', '5'))

    # Burst project hint after user sends classify text before photos arrive
    WA_BURST_PROJECT_TTL_S = int(os.environ.get('WA_BURST_PROJECT_TTL_S', '120'))

    # Poll NAS mount for new folders/files → web projects/records (0 = disabled)
    NAS_SYNC_INTERVAL_S = int(os.environ.get('NAS_SYNC_INTERVAL_S', 60))

    # Stale job recovery — jobs with no worker progress beyond this are auto-failed
    JOB_STALE_MINUTES = int(os.environ.get('JOB_STALE_MINUTES', 30))
    JOB_RECOVERY_INTERVAL_MINUTES = int(os.environ.get('JOB_RECOVERY_INTERVAL_MINUTES', 5))


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    MONGO_URI = 'mongodb://localhost:27017/signhouse_test'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
