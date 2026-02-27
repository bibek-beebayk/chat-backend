from .base import *
import os

SECRET_KEY = 'ih(u#bi@vd-0jog$myq824vrh9j5+*!2_w12)$u1x-29khfx%6'

DEBUG = False

# Require ALLOWED_HOSTS for staging
ALLOWED_HOSTS = [
    "chat-backend-staging.up.railway.app"
]


# Staging Database (Expects Env Vars)
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

# Staging Channels (Expects Env Vars for Redis)
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

# Kept the frontend URLs in staging
CORS_ALLOWED_ORIGINS = [
    "https://chat-frontend-nu-five.vercel.app", 
    "https://chat-backend-staging.up.railway.app",
    "http://127.0.0.1:3000",
    "http://localhost:3000"
]
CSRF_TRUSTED_ORIGINS = [
    "https://chat-frontend-nu-five.vercel.app", 
    "https://chat-backend-staging.up.railway.app",
    "http://127.0.0.1:3000",
    "http://localhost:3000"
]

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

# AWS / Cloudflare R2 Settings keys
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME")
AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL")


import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

# Using same Sentry DSN but with environment="staging"
sentry_sdk.init(
    dsn="https://a5888a2b1232e5d70b297e00f1f97023@o4505908028702720.ingest.us.sentry.io/4507084460589056",
    integrations=[DjangoIntegration()],
    send_default_pii=True,
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
    environment="staging", # Changed to staging
)

# ZeptoMail Configuration
EMAIL_BACKEND = 'zoho_zeptomail.backend.zeptomail_backend.ZohoZeptoMailEmailBackend'
ZEPTOMAIL_API_KEY = "GkDdjPjeqQBKwVzCoY6xNdRTbZQ0tJPrF8jgMsoC80Av791ds0wefcFBkXUuzDYa7XPDAlfLdL938DPc57WCcSwpI3qvcUTuOpwzGB+edd0FvHvXUPiy9P9gXkbKmvGpNw9m6h8x9i9g4A=="
ZEPTO_ORG_MAIL_TOKEN = ZEPTOMAIL_API_KEY
ZEPTOMAIL_FROM = "noreply@hrlzone.com"
DEFAULT_FROM_EMAIL = ZEPTOMAIL_FROM
SERVER_EMAIL = ZEPTOMAIL_FROM

MAIN_WEBSITE_URL = "https://community.hrlzone.com"

PLAYER_DATA_API_BASE_URL = os.environ.get("PLAYER_DATA_API_BASE_URL")
PLAYER_DATA_API_KEY = os.environ.get("PLAYER_DATA_API_KEY")
