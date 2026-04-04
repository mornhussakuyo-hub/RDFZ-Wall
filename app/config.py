from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / 'app'
TEMPLATE_DIR = APP_DIR / 'templates'
STATIC_DIR = APP_DIR / 'static'
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv('DATABASE_URL', f"sqlite:///{(DATA_DIR / 'wall.db').as_posix()}")
SECRET_KEY = os.getenv('SECRET_KEY', 'change-me-in-production')
SESSION_COOKIE_NAME = os.getenv('SESSION_COOKIE_NAME', 'wall_session')
UPLOAD_DIR = Path(os.getenv('UPLOAD_DIR', (STATIC_DIR / 'uploads').as_posix()))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_FILES = int(os.getenv('MAX_UPLOAD_FILES', '9'))
MAX_SINGLE_FILE_MB = int(os.getenv('MAX_SINGLE_FILE_MB', '10'))
MAX_VIDEO_FILES = int(os.getenv('MAX_VIDEO_FILES', '3'))
MAX_SINGLE_VIDEO_MB = int(os.getenv('MAX_SINGLE_VIDEO_MB', '100'))
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.m4v'}
SITE_NAME = os.getenv('SITE_NAME', '人亚校园墙')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
