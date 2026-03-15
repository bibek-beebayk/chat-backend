import re
from urllib.parse import urlsplit, urlunsplit
from django.conf import settings
from django.core.files.storage import default_storage


_URL_ATTR_PATTERN = re.compile(
    r'(?P<prefix>\b(?:src|href)=["\'])(?P<url>https?://[^"\']+)(?P<suffix>["\'])',
    re.IGNORECASE,
)


def normalize_signed_media_urls(content: str) -> str:
    """
    Remove expiring signature query params from embedded media URLs
    (e.g. X-Amz-*), so content keeps working when signatures expire.
    """
    if not content:
        return content

    media_url = (getattr(settings, 'MEDIA_URL', '') or '').strip()
    bucket_name = (getattr(settings, 'AWS_STORAGE_BUCKET_NAME', '') or '').strip()

    def _extract_storage_key(url: str) -> str | None:
        parts = urlsplit(url)
        path = parts.path or ''
        normalized = path.lstrip('/')

        if '/uploads/' in f'/{normalized}':
            idx = normalized.find('uploads/')
            if idx >= 0:
                return normalized[idx:]

        if media_url and normalized.startswith(media_url.lstrip('/')):
            media_relative = normalized[len(media_url.lstrip('/')):]
            media_relative = media_relative.lstrip('/')
            if media_relative.startswith('uploads/'):
                return media_relative

        if bucket_name and normalized.startswith(f'{bucket_name}/uploads/'):
            return normalized[len(bucket_name) + 1 :]

        return None

    def _replace(match: re.Match) -> str:
        url = match.group('url')
        parts = urlsplit(url)
        query = parts.query or ''
        has_signature = 'X-Amz-Algorithm=' in query or 'X-Amz-Signature=' in query
        storage_key = _extract_storage_key(url)

        if storage_key:
            try:
                fresh_url = default_storage.url(storage_key)
                return f"{match.group('prefix')}{fresh_url}{match.group('suffix')}"
            except Exception:
                pass

        if has_signature:
            clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, '', parts.fragment))
            return f"{match.group('prefix')}{clean_url}{match.group('suffix')}"

        return match.group(0)

    return _URL_ATTR_PATTERN.sub(_replace, content)
