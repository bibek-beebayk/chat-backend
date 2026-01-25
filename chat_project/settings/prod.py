from .base import *
import os

SECRET_KEY = 'ih(u#bi@vd-0jog$myq824vrh9j5+*!2_w12)$u1x-29khfx%6'

DEBUG = False

# Require ALLOWED_HOSTS for production
ALLOWED_HOSTS = ["chat-backend-production-c7cd.up.railway.app"]


# Production Database (Expects Env Vars)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# Production Channels (Expects Env Vars for Redis)
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [(os.environ.get('REDISHOST'), os.environ.get('REDISPORT', 6379))],
        },
    },
}

# Security Enhancements
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Cross-Site Cookie Settings (Required for Vercel -> Railway)
SESSION_COOKIE_SAMESITE = 'None'
CSRF_COOKIE_SAMESITE = 'None'


# CORS/CSRF (Restrictive)
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = ["https://chat-frontend-nu-five.vercel.app", "https://chat-backend-production-c7cd.up.railway.app"]
CSRF_TRUSTED_ORIGINS = ["https://chat-frontend-nu-five.vercel.app", "https://chat-backend-production-c7cd.up.railway.app"]

# Static Files (Whitenoise)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
