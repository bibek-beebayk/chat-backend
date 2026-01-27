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
# Check for REDIS_URL (Railway standard) or fallback to host/port
REDIS_URL = os.environ.get('REDIS_URL')

if REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                "hosts": [REDIS_URL],
            },
        },
    }
else:
    # Fallback to granular variables
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                "hosts": [(os.environ.get('REDISHOST', 'localhost'), os.environ.get('REDISPORT', 6379))],
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
# Static Files (Whitenoise) & Media Files (Cloudflare R2)
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "endpoint_url": os.environ.get("AWS_S3_ENDPOINT_URL"),
            "access_key": os.environ.get("AWS_ACCESS_KEY_ID"),
            "secret_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
            "bucket_name": os.environ.get("AWS_STORAGE_BUCKET_NAME"),
            "region_name": "auto",  # R2 uses 'auto'
            "default_acl": None,    # R2 doesn't support ACLs usually
            "signature_version": "s3v4",
            "querystring_auth": True, # Presigned URLs for private files
        },
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# AWS / Cloudflare R2 Settings keys (for completeness if backend relies on them globally)
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME")
AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL")


import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

sentry_sdk.init(
    dsn="https://a5888a2b1232e5d70b297e00f1f97023@o4505908028702720.ingest.us.sentry.io/4507084460589056",
    integrations=[DjangoIntegration()],
    # If you wish to associate users to errors (assuming you are using
    # django.contrib.auth) you may enable sending PII data.
    send_default_pii=True,
    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production.
    traces_sample_rate=1.0,
    # Set profiles_sample_rate to 1.0 to profile 100%
    # of sampled transactions.
    # We recommend adjusting this value in production.
    profiles_sample_rate=1.0,
    environment="chat",
)

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.zoho.com.au' 
EMAIL_PORT = 587 
EMAIL_USE_TLS = True 
EMAIL_USE_SSL = False
EMAIL_HOST_USER = 'support@hi-rollin.online'
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
