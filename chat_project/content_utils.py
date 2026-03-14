import re
from urllib.parse import urlsplit, urlunsplit


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

    def _replace(match: re.Match) -> str:
        url = match.group('url')
        parts = urlsplit(url)
        query = parts.query or ''
        if 'X-Amz-Algorithm=' not in query and 'X-Amz-Signature=' not in query:
            return match.group(0)
        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, '', parts.fragment))
        return f"{match.group('prefix')}{clean_url}{match.group('suffix')}"

    return _URL_ATTR_PATTERN.sub(_replace, content)
