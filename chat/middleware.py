from django.contrib.auth.models import AnonymousUser
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.sessions.models import Session
from django.contrib.auth import get_user_model
from urllib.parse import parse_qs

@database_sync_to_async
def get_user_from_session_key(session_key):
    try:
        from importlib import import_module
        from django.conf import settings
        engine = import_module(settings.SESSION_ENGINE)
        session_store = engine.SessionStore(session_key)
        
        user_id = session_store.get('_auth_user_id')
        if not user_id:
            return AnonymousUser()
            
        User = get_user_model()
        return User.objects.get(id=user_id)
    except Exception:
        return AnonymousUser()

class QueryAuthMiddleware(BaseMiddleware):
    """
    Custom middleware to authenticate users via query parameter 'token' in WebSocket URL.
    This bypasses cookie restrictions (ITP) on iOS/Brave by passing the session key explicitly.
    """
    async def __call__(self, scope, receive, send):
        # Only handle websocket connections
        if scope['type'] != 'websocket':
            return await super().__call__(scope, receive, send)

        # Parse query string
        query_string = scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]

        # Use token if provided, otherwise fall back to cookies (AuthMiddlewareStack)
        if token:
            user = await get_user_from_session_key(token)
            if user and user.is_authenticated:
                scope['user'] = user
                
        return await super().__call__(scope, receive, send)
