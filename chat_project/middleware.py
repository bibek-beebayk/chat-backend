import logging
import os
from django.conf import settings

# Configure logger manually to ensure it writes where we want
log_file_path = os.path.join(settings.BASE_DIR, 'debug_api.log')
logger = logging.getLogger('api_logger')
logger.setLevel(logging.DEBUG)

# File handler
handler = logging.FileHandler(log_file_path)
handler.setLevel(logging.DEBUG)

# Formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Add handler if not already present to avoid duplicates on reload
if not logger.handlers:
    logger.addHandler(handler)

class APILogMiddleware:
    """
    Middleware to log all API requests and responses to a file.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only log API requests to reduce noise, or log everything?
        # User said "all api requests", so let's filter for /api/
        if request.path.startswith('/api/'):
            self.log_request(request)

        response = self.get_response(request)

        if request.path.startswith('/api/'):
            self.log_response(request, response)

        return response

    def log_request(self, request):
        try:
            # Try to read body without consuming it if possible, or just log basic info
            # Django request.body consumes the stream. Ideally we shouldn't touch it unless necessary.
            # However, for debugging, seeing the body is useful.
            # Safest is to just log method, path, and user.
            user = getattr(request, 'user', 'Anonymous')
            logger.info(f"REQUEST: {request.method} {request.path} - User: {user}")
            # If you really need body, you'd need to handle stream consumption. skipping for safety/performance unless requested.
            # logger.debug(f"Body: {request.body.decode('utf-8')[:1000]}") # Truncated
        except Exception as e:
            logger.error(f"Error logging request: {e}")

    def log_response(self, request, response):
        try:
            status_code = response.status_code
            content = getattr(response, 'content', b'')
            
            # Try decoding content for logging if text-based
            try:
                 log_content = content.decode('utf-8')[:2000] # Truncate large responses
            except:
                 log_content = "<binary or non-utf8 content>"

            logger.info(f"RESPONSE: {status_code} {request.path} - Content: {log_content}")
        except Exception as e:
            logger.error(f"Error logging response: {e}")
