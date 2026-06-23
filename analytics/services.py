import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings

from .models import AnalyticsEvent


SENSITIVE_QUERY_KEYS = {
    'access',
    'auth',
    'credential',
    'otp',
    'password',
    'refresh',
    'reset_token',
    'signature',
    'token',
}


def track_event(
    *,
    request=None,
    user=None,
    event_type=AnalyticsEvent.EVENT_CUSTOM,
    event_name='',
    path='',
    full_path='',
    referrer='',
    anonymous_id='',
    session_id='',
    source='',
    medium='',
    campaign='',
    metadata=None,
):
    """Create an analytics event without letting analytics failures break product flows."""
    try:
        request_user = getattr(request, 'user', None)
        actor = user or (request_user if getattr(request_user, 'is_authenticated', False) else None)
        request_meta = getattr(request, 'META', {}) if request is not None else {}
        user_agent = request_meta.get('HTTP_USER_AGENT', '')
        parsed_agent = parse_user_agent(user_agent)
        query_source = extract_utm_from_request(request)
        geo = extract_geo(request_meta)

        clean_path = sanitize_path(path or (getattr(request, 'path', '') if request is not None else ''))
        clean_full_path = sanitize_url(full_path or get_full_path(request))

        meta_payload = metadata or {}
        inferred_user_type = ''
        if not actor and meta_payload.get('user_type') in {'player', 'agent', 'staff'}:
            inferred_user_type = meta_payload.get('user_type')

        return AnalyticsEvent.objects.create(
            user=actor if getattr(actor, 'is_authenticated', True) else None,
            anonymous_id=(anonymous_id or '').strip()[:80],
            session_id=(session_id or '').strip()[:80],
            event_type=event_type,
            event_name=(event_name or '').strip()[:120],
            user_type=(getattr(actor, 'user_type', '') or inferred_user_type or '')[:20],
            path=clean_path[:255],
            full_path=clean_full_path[:500],
            method=(getattr(request, 'method', '') if request is not None else '')[:12],
            referrer=sanitize_url(referrer or request_meta.get('HTTP_REFERER', ''))[:500],
            source=(source or query_source.get('source', ''))[:120],
            medium=(medium or query_source.get('medium', ''))[:120],
            campaign=(campaign or query_source.get('campaign', ''))[:160],
            device_type=parsed_agent['device_type'],
            browser=parsed_agent['browser'],
            os=parsed_agent['os'],
            country=geo['country'],
            region=geo['region'],
            city=geo['city'],
            ip_hash=hash_ip(get_client_ip(request_meta)),
            metadata=meta_payload,
        )
    except Exception:
        return None


def get_full_path(request):
    if request is None:
        return ''
    try:
        return request.get_full_path()
    except Exception:
        return getattr(request, 'path', '')


def sanitize_path(value):
    if not value:
        return ''
    split = urlsplit(value)
    return split.path or value.split('?', 1)[0]


def sanitize_url(value):
    if not value:
        return ''
    split = urlsplit(value)
    safe_query = [
        (key, '[redacted]' if key.lower() in SENSITIVE_QUERY_KEYS else query_value)
        for key, query_value in parse_qsl(split.query, keep_blank_values=True)
    ]
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(safe_query), split.fragment))


def extract_utm_from_request(request):
    if request is None:
        return {}
    return {
        'source': request.query_params.get('utm_source', '') or request.query_params.get('source', ''),
        'medium': request.query_params.get('utm_medium', ''),
        'campaign': request.query_params.get('utm_campaign', ''),
    }


def get_client_ip(meta):
    forwarded = meta.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return meta.get('REMOTE_ADDR', '')


def hash_ip(ip_address):
    if not ip_address:
        return ''
    salt = getattr(settings, 'SECRET_KEY', '')
    return hashlib.sha256(f'{salt}:{ip_address}'.encode('utf-8')).hexdigest()


def extract_geo(meta):
    return {
        'country': (meta.get('HTTP_CF_IPCOUNTRY') or meta.get('HTTP_X_VERCEL_IP_COUNTRY') or '')[:80],
        'region': (meta.get('HTTP_X_VERCEL_IP_COUNTRY_REGION') or '')[:120],
        'city': (meta.get('HTTP_X_VERCEL_IP_CITY') or '')[:120],
    }


def parse_user_agent(user_agent):
    agent = (user_agent or '').lower()
    if 'mobile' in agent or 'android' in agent or 'iphone' in agent:
        device_type = 'mobile'
    elif 'ipad' in agent or 'tablet' in agent:
        device_type = 'tablet'
    elif agent:
        device_type = 'desktop'
    else:
        device_type = ''

    browser = 'Other'
    if 'edg/' in agent:
        browser = 'Edge'
    elif 'chrome/' in agent and 'chromium' not in agent:
        browser = 'Chrome'
    elif 'safari/' in agent and 'chrome/' not in agent:
        browser = 'Safari'
    elif 'firefox/' in agent:
        browser = 'Firefox'

    os_name = 'Other'
    if 'windows' in agent:
        os_name = 'Windows'
    elif 'android' in agent:
        os_name = 'Android'
    elif 'iphone' in agent or 'ipad' in agent or 'ios' in agent:
        os_name = 'iOS'
    elif 'mac os' in agent or 'macintosh' in agent:
        os_name = 'macOS'
    elif 'linux' in agent:
        os_name = 'Linux'

    return {
        'device_type': device_type,
        'browser': browser,
        'os': os_name,
    }
