"""
ASGI config for chat_project project.
"""

import os
import django
from django.core.asgi import get_asgi_application
from chat_project.env_loader import load_local_env


load_local_env()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chat_project.settings')
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from chat import routing


django_asgi_app = get_asgi_application()

from chat.middleware import QueryAuthMiddleware

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": QueryAuthMiddleware(
        URLRouter(
            routing.websocket_urlpatterns
        )
    ),
})
