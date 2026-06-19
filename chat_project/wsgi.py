"""
WSGI config for chat_project project.
"""

import os
from django.core.wsgi import get_wsgi_application
from chat_project.env_loader import load_local_env

load_local_env()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chat_project.settings')

application = get_wsgi_application()
