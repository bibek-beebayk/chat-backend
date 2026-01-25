"""
Development settings for chat_project.
"""

from .base import *
import os

SECRET_KEY = 'ih(u#bi@vd-0jog$myq824vrh9j5+*!2_w12)$u1x-29khfx%6'

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'betunnel.worldstories.net', '*']


# Database
# Default to SQLite/Postgres as per original settings.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": os.environ.get("PGDATABASE", "chat_db"),
        "USER": os.environ.get("PGUSER", "postgres"),
        "PASSWORD": os.environ.get("PGPASSWORD", "postgres"),
        "HOST": os.environ.get("PGHOST", ""),
        "PORT": os.environ.get("PGPORT", ""),
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
    "https://betunnel.worldstories.net",
    "https://chatfe.worldstories.net"
]

CORS_ALLOW_CREDENTIALS = True

# CSRF settings
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://betunnel.worldstories.net",
    "https://chatfe.worldstories.net"
]

# Session settings
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = True  # Set to True in production with HTTPS
SESSION_COOKIE_DOMAIN = '.worldstories.net'

# CSRF settings
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False 
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_DOMAIN = '.worldstories.net'

# Import local env settings
try:
    from .env import *
except ImportError:
    pass
