import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


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
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max file size
    ALLOWED_EXTENSIONS = {'pdf', 'xlsx', 'xls'}
    
    # Tesseract Configuration
    TESSERACT_CMD = os.environ.get('TESSERACT_CMD', '/usr/local/bin/tesseract')
    
    # Title Block Extraction Configuration (for floor plan title extraction)
    TITLE_REGION_X_START = int(os.environ.get('TITLE_REGION_X_START', 60))  # 60% from left
    TITLE_REGION_Y_START = int(os.environ.get('TITLE_REGION_Y_START', 85))  # 85% from top
    TITLE_REGION_WIDTH = int(os.environ.get('TITLE_REGION_WIDTH', 40))      # 40% of image width
    TITLE_REGION_HEIGHT = int(os.environ.get('TITLE_REGION_HEIGHT', 15))    # 15% of image height
    
    # CORS Configuration
    ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', 'http://localhost:3000').split(',')


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
