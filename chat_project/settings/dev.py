"""
Development settings for chat_project.
"""

from .base import *
import os

SECRET_KEY = 'ih(u#bi@vd-0jog$myq824vrh9j5+*!2_w12)$u1x-29khfx%6'

DEBUG = True

# Set this in local env when using devtunnel, e.g.
# PUBLIC_BACKEND_URL=https://<your-tunnel>.devtunnels.ms
PUBLIC_BACKEND_URL = os.environ.get('PUBLIC_BACKEND_URL', '').strip()

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    'betunnel.worldstories.net',
    '5dn4bj2m-8000.inc1.devtunnels.ms',
    'dev.hrlzone.com',
    'fedev.hrlzone.com',
    '*',
]
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# Database
# Default to SQLite/Postgres as per original settings.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("PGDATABASE", "chat_db"),
        "USER": os.environ.get("PGUSER", "postgres"),
        "PASSWORD": os.environ.get("PGPASSWORD", "beebayk"),
        "HOST": os.environ.get("PGHOST", "127.0.0.1"),
        "PORT": os.environ.get("PGPORT", "5432"),
        "ATOMIC_REQUESTS": True,
    }
}

# Channels configuration
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [(os.environ.get('REDIS_HOST', 'localhost'), 6379)],
        },
    },
}

# CORS settings
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://betunnel.worldstories.net",
    "https://chatfe.worldstories.net",
    "https://5dn4bj2m-8000.inc1.devtunnels.ms",
    "https://fedev.hrlzone.com",
    "https://dev.hrlzone.com",
]

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://[a-z0-9-]+\.devtunnels\.ms$",
    r"^https://[a-z0-9-]+\.hrlzone\.com$",
]

# CSRF settings
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://betunnel.worldstories.net",
    "https://chatfe.worldstories.net",
    "https://5dn4bj2m-8000.inc1.devtunnels.ms",
    "https://fedev.hrlzone.com",
    "https://dev.hrlzone.com",
]

# Session settings
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
# SESSION_COOKIE_DOMAIN = '.worldstories.net' # Disabled for local dev

# CSRF settings
CSRF_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = False 
CSRF_COOKIE_SAMESITE = 'Lax'
# CSRF_COOKIE_DOMAIN = '.worldstories.net' # Disabled for local dev

# Import local env settings
try:
    from .env import *
except ImportError:
    pass


# ZeptoMail Configuration
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
ZEPTOMAIL_API_KEY = "GkDdjPjeqQBKwVzCoY6xNdRTbZQ0tJPrF8jgMsoC80Av791ds0wefcFBkXUuzDYa7XPDAlfLdL938DPc57WCcSwpI3qvcUTuOpwzGB+edd0FvHvXUPiy9P9gXkbKmvGpNw9m6h8x9i9g4A=="
ZEPTO_ORG_MAIL_TOKEN = ZEPTOMAIL_API_KEY
ZEPTOMAIL_FROM = "noreply@hrlzone.com"
DEFAULT_FROM_EMAIL = ZEPTOMAIL_FROM
SERVER_EMAIL = ZEPTOMAIL_FROM

MAIN_WEBSITE_URL = "https://chatfe.worldstories.net"

PLAYER_DATA_API_BASE_URL = "https://dev.api.hi-rollin.online/api/v1"
PLAYER_DATA_API_KEY = "PfDAY2Q3gnlTU6hHr1rJOJJ3Ti2SyAW17m2fSEl9"
