from rest_framework.authentication import BaseAuthentication
from django.contrib.sessions.models import Session
from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework import exceptions

class SessionTokenAuthentication(BaseAuthentication):
    """
    Authenticate using a Django Session ID passed in the 'Authorization' header.
    Header format: 'Authorization: Session <session_key>'
    """
    def authenticate(self, request):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return None

        try:
            prefix, session_key = auth_header.split()
        except ValueError:
            return None

        if prefix.lower() != 'session':
            return None

        return self.authenticate_credentials(request, session_key)

    def authenticate_credentials(self, request, session_key):
        from importlib import import_module
        engine = import_module(settings.SESSION_ENGINE)
        session_store = engine.SessionStore(session_key)

        if not session_store.exists(session_key):
            raise exceptions.AuthenticationFailed('Invalid session token')

        try:
            user_id = session_store.get('_auth_user_id')
            if not user_id:
                raise exceptions.AuthenticationFailed('Invalid session user')
            
            User = get_user_model()
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, KeyError):
            raise exceptions.AuthenticationFailed('Invalid user')

        if not user.is_active:
            raise exceptions.AuthenticationFailed('User inactive')
            
        # Ensure request.session is populated for consistency
        request.session = session_store
        
        return (user, session_key)
