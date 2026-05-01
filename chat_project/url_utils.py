from urllib.parse import urlsplit, urlunsplit
from django.conf import settings


def build_public_absolute_uri(request, url: str) -> str:
    """
    Build an absolute URL that respects reverse-proxy headers.

    Dev tunnel/proxy setups sometimes leave Django seeing localhost as host.
    In that case, prefer X-Forwarded-Host / X-Forwarded-Proto when present.
    """
    if not url:
        return url

    # Already absolute.
    if url.startswith('http://') or url.startswith('https://'):
        return url

    public_base = (getattr(settings, 'PUBLIC_BACKEND_URL', '') or '').rstrip('/')
    public_base_parts = urlsplit(public_base) if public_base else None

    if not request:
        if public_base and url.startswith('/'):
            return f'{public_base}{url}'
        return url

    absolute = request.build_absolute_uri(url)
    parts = urlsplit(absolute)
    hostname = (parts.hostname or "").lower()

    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        return absolute

    forwarded_host = (request.META.get("HTTP_X_FORWARDED_HOST") or "").strip()
    if not forwarded_host:
        if public_base:
            return urlunsplit(
                (
                    public_base_parts.scheme,
                    public_base_parts.netloc,
                    parts.path,
                    parts.query,
                    parts.fragment,
                )
            )
        return absolute

    forwarded_proto_raw = (request.META.get("HTTP_X_FORWARDED_PROTO") or "").strip()
    forwarded_proto = forwarded_proto_raw.split(",")[0].strip() if forwarded_proto_raw else ""
    scheme = forwarded_proto or parts.scheme or "https"

    return urlunsplit((scheme, forwarded_host, parts.path, parts.query, parts.fragment))
