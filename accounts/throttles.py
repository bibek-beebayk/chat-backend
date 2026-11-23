import hashlib

from rest_framework.throttling import SimpleRateThrottle

from analytics.services import get_client_ip


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _client_ip(request, fallback_ident: str) -> str:
    ip = get_client_ip(request.META)
    return ip or fallback_ident


class LoginIPThrottle(SimpleRateThrottle):
    scope = 'auth_login_ip'

    def get_cache_key(self, request, view):
        ident = _client_ip(request, self.get_ident(request))
        if not ident:
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident,
        }


class LoginIdentifierThrottle(SimpleRateThrottle):
    scope = 'auth_login_identifier'

    def get_cache_key(self, request, view):
        raw = request.data.get('username') if hasattr(request, 'data') else ''
        identifier = str(raw or '').strip().lower()
        if not identifier:
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': _hash_identifier(identifier),
        }


class OTPThrottle(SimpleRateThrottle):
    scope = 'auth_otp'

    def get_cache_key(self, request, view):
        ip = _client_ip(request, self.get_ident(request))
        raw_email = ''
        if hasattr(request, 'data'):
            raw_email = request.data.get('email') or request.data.get('username') or ''
        email = str(raw_email).strip().lower()
        if not ip and not email:
            return None
        key_material = f'{ip}:{_hash_identifier(email) if email else "anon"}'
        return self.cache_format % {
            'scope': self.scope,
            'ident': key_material,
        }
