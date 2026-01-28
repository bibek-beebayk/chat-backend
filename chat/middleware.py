from django.contrib.auth.models import AnonymousUser
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from urllib.parse import parse_qs
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from jwt import decode as jwt_decode
from django.conf import settings

@database_sync_to_async
def get_user_from_jwt(token_key):
    try:
        UntypedToken(token_key)
    except (InvalidToken, TokenError):
        return AnonymousUser()
        
    try:
        decoded_data = jwt_decode(token_key, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = decoded_data.get('user_id')
        User = get_user_model()
        return User.objects.get(id=user_id)
    except Exception:
        return AnonymousUser()

class QueryAuthMiddleware(BaseMiddleware):
    """
    Custom middleware to authenticate users via query parameter 'token' in WebSocket URL.
    Expected URL: ws://...?token=<access_token>
    """
    async def __call__(self, scope, receive, send):
        # Only handle websocket connections
        if scope['type'] != 'websocket':
            return await super().__call__(scope, receive, send)

        # Parse query string
        query_string = scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]

        # Use token if provided
        if token:
            user = await get_user_from_jwt(token)
            if user:
                scope['user'] = user
                
        return await super().__call__(scope, receive, send)
