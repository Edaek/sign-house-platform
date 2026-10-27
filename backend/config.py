import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# override=True: paths with spaces in .env must win over a truncated shell export.
load_dotenv(Path(__file__).resolve().parent / '.env', override=True)


def _normalize_cors_origin(origin: str) -> str:
    """Browsers send Origin as scheme+host only; strip accidental path suffixes in env."""
    origin = origin.strip()
    if not origin or origin == '*':
        return origin
    if not origin.startswith(('http://', 'https://')):
        return origin
    from urllib.parse import urlparse

    parsed = urlparse(origin)
    if not parsed.scheme or not parsed.netloc:
        return origin
    return f'{parsed.scheme}://{parsed.netloc}'


def _parse_allowed_origins(raw: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(','):
        normalized = _normalize_cors_origin(part)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Server Configuration
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 5002))
    
    # JWT Configuration
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        hours=int(os.environ.get('JWT_ACCESS_TOKEN_HOURS', '24'))
    )
    
    # MongoDB Configuration (append serverSelectionTimeoutMS in URI if missing — fail fast on Atlas/network)
    _mongo_default = 'mongodb://localhost:27017/signhouse_dev'
    MONGO_URI = os.environ.get('MONGO_URI', _mongo_default)
    if MONGO_URI and 'serverSelectionTimeoutMS' not in MONGO_URI:
        sep = '&' if '?' in MONGO_URI else '?'
        MONGO_URI = f'{MONGO_URI}{sep}serverSelectionTimeoutMS=10000'
    
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
    
    # CORS Configuration (Origin header never includes path — use https://xerosumio.github.io)
    ALLOWED_ORIGINS = _parse_allowed_origins(
        os.environ.get(
            'ALLOWED_ORIGINS',
            'http://localhost:3000,http://127.0.0.1:3000',
        )
    )
    
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

    # auto = legacy WhatsApp fuzzy/AI classify; loomy = intake only + Mattermost @signhouseloomy
    WA_INBOUND_CLASSIFY_MODE = os.environ.get('WA_INBOUND_CLASSIFY_MODE', 'auto').strip().lower()
    MATTERMOST_POOL_WEBHOOK_URL = os.environ.get('MATTERMOST_POOL_WEBHOOK_URL', '').strip()
    LOOMY_POOL_NOTIFY_ENABLED = os.environ.get('LOOMY_POOL_NOTIFY_ENABLED', '').strip().lower()
    LOOMY_WA_POOL_ACK = os.environ.get('LOOMY_WA_POOL_ACK', '').strip()
    LOOMY_MATTERMOST_NOTIFY = os.environ.get('LOOMY_MATTERMOST_NOTIFY', '').strip().lower()
    LOOMY_WA_AGENT_DEBOUNCE_S = float(os.environ.get('LOOMY_WA_AGENT_DEBOUNCE_S', '3'))
    LOOMY_WA_MCP_MAX_ROUNDS = int(os.environ.get('LOOMY_WA_MCP_MAX_ROUNDS', '3'))
    LOOMY_WA_MCP_TOOLS_ALLOW = os.environ.get('LOOMY_WA_MCP_TOOLS_ALLOW', '').strip()
    LOOMY_WA_MCP_TOOLS_DENY = os.environ.get('LOOMY_WA_MCP_TOOLS_DENY', '').strip()
    LOOMY_WA_INPROCESS_TOOLS = os.environ.get('LOOMY_WA_INPROCESS_TOOLS', 'true').strip().lower()
    SIGN_HOUSE_INTERNAL_API_URL = os.environ.get('SIGN_HOUSE_INTERNAL_API_URL', '').strip()

    # Poll NAS mount for new folders/files → web projects/records (0 = disabled)
    NAS_SYNC_INTERVAL_S = int(os.environ.get('NAS_SYNC_INTERVAL_S', 60))

    # Stale job recovery — jobs with no worker progress beyond this are auto-failed
    JOB_STALE_MINUTES = int(os.environ.get('JOB_STALE_MINUTES', 30))
    JOB_RECOVERY_INTERVAL_MINUTES = int(os.environ.get('JOB_RECOVERY_INTERVAL_MINUTES', 5))

    # Hosted sign-house-wa MCP tools (same process when unset → this server's /api)
    MCP_HTTP_MOUNT_PREFIX = os.environ.get('MCP_HTTP_MOUNT_PREFIX', '/mcp')
    SIGN_HOUSE_API_URL = os.environ.get('SIGN_HOUSE_API_URL', 'http://127.0.0.1:5002/api')
    # MCP HTTP auth: user = Bearer only (Loom per-user token); fallback = allow SIGN_HOUSE_JWT / MCP_BOT_*
    MCP_AUTH_MODE = os.environ.get('MCP_AUTH_MODE', 'fallback').strip().lower()


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
