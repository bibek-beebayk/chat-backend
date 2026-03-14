import json
import logging
from typing import Iterable
from urllib import error, request

from django.conf import settings

logger = logging.getLogger(__name__)


def trigger_blog_frontend_revalidation(paths: Iterable[str]) -> bool:
    """
    Trigger on-demand ISR revalidation in blog-frontend.
    Returns False silently when webhook is not configured.
    """
    endpoint = getattr(settings, 'BLOG_FRONTEND_REVALIDATE_URL', '').strip()
    token = getattr(settings, 'BLOG_FRONTEND_REVALIDATE_TOKEN', '').strip()
    if not endpoint or not token:
        return False

    normalized_paths = sorted(
        {
            path.strip()
            for path in paths
            if isinstance(path, str) and path.strip().startswith('/')
        }
    )
    if not normalized_paths:
        return False

    payload = json.dumps({'paths': normalized_paths}).encode('utf-8')
    req = request.Request(
        endpoint,
        data=payload,
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        },
    )

    try:
        with request.urlopen(req, timeout=5) as response:
            return 200 <= response.status < 300
    except error.HTTPError as exc:
        logger.warning('Blog frontend revalidation failed (HTTP %s): %s', exc.code, exc.reason)
    except error.URLError as exc:
        logger.warning('Blog frontend revalidation failed: %s', exc.reason)
    except Exception:
        logger.exception('Unexpected error while revalidating blog frontend.')
    return False
