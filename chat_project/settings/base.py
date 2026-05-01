from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent.parent

ALLOWED_HOSTS = []

# Application definition
INSTALLED_APPS = [
    'daphne',  # Must be first for channels
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'channels',
    'accounts',
    'chat',
    'posts',
    'blog',
    'ckeditor',
    'ckeditor_uploader',
    'rest_framework_simplejwt.token_blacklist',
    'events',
    'notifications',
    'analytics',
    'social',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'chat_project.middleware.APILogMiddleware',
]

ROOT_URLCONF = 'chat_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'chat_project.wsgi.application'
ASGI_APPLICATION = 'chat_project.asgi.application'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
CKEDITOR_UPLOAD_PATH = 'uploads/'
CKEDITOR_RESTRICT_BY_USER = False
CKEDITOR_ALLOW_NONIMAGE_FILES = False
if (
    os.environ.get('AWS_STORAGE_BUCKET_NAME')
    and os.environ.get('AWS_S3_ENDPOINT_URL')
    and os.environ.get('CKEDITOR_PUBLIC_UPLOADS', 'false').lower() == 'true'
):
    CKEDITOR_STORAGE_BACKEND = 'chat_project.storage_backends.CKEditorPublicStorage'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'accounts.User'

# REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication', # Keep session for admin/browseable API if needed, or remove for pure API
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'EXCEPTION_HANDLER': 'chat_project.exceptions.custom_exception_handler',
    'DEFAULT_RENDERER_CLASSES': [
        'chat_project.renderers.StandardResponseRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
}

from datetime import timedelta
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'notifications': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Blog frontend ISR revalidation webhook (optional).
BLOG_FRONTEND_REVALIDATE_URL = os.environ.get('BLOG_FRONTEND_REVALIDATE_URL', '')
BLOG_FRONTEND_REVALIDATE_TOKEN = os.environ.get('BLOG_FRONTEND_REVALIDATE_TOKEN', '')

# Optional absolute backend URL used when serializers need to build media URLs
# without request context (e.g. token/login responses).
PUBLIC_BACKEND_URL = os.environ.get('PUBLIC_BACKEND_URL', '').strip()
