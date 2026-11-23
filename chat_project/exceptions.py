from rest_framework.views import exception_handler
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework import status
import logging
import math

logger = logging.getLogger(__name__)

_GENERIC_DRF_CODES = {
    "authentication_failed",
    "not_authenticated",
    "permission_denied",
    "not_found",
    "error",
    "invalid",
    "parse_error",
    "method_not_allowed",
    "not_acceptable",
    "unsupported_media_type",
    "throttled",
}


def _extract_custom_code(exc):
    explicit = getattr(exc, "custom_code", None)
    if explicit:
        return explicit

    default_code = getattr(exc, "default_code", None)
    if isinstance(default_code, str) and default_code and default_code not in _GENERIC_DRF_CODES:
        return default_code

    if hasattr(exc, "get_codes"):
        codes = exc.get_codes()
        if isinstance(codes, str) and codes and codes not in _GENERIC_DRF_CODES:
            return codes

    return None


def custom_exception_handler(exc, context):
    """
    Custom exception handler that standardizes error responses.
    Response format:
    {
        "status": "error",
        "code": "error_code_string",
        "message": "Human readable summary",
        "errors": { "field": ["detail"] },
    }
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)

    # Initialize standard structure
    data = {
        "status": "error",
        "code": "internal_error",
        "message": "An unexpected error occurred",
        "errors": None,
    }

    if response is not None:
        if isinstance(exc, Throttled):
            retry_after = max(1, math.ceil(exc.wait)) if exc.wait is not None else 60
            data["code"] = "throttled"
            data["message"] = "Too many login attempts. Please wait before trying again."
            data["errors"] = None
            data["retry_after"] = retry_after
            response["Retry-After"] = str(retry_after)
            response.data = data
            return response

        custom_code = _extract_custom_code(exc)
        data["code"] = custom_code or exc.__class__.__name__

        # Handle specific DRF standard structures
        if isinstance(response.data, list):
            # ["Error message 1", "Error message 2"]
            data["message"] = response.data[0]
            data["errors"] = {"non_field_errors": response.data}

        elif isinstance(response.data, dict):
            # {"field": ["Error"], "detail": "Auth failed"}

            # Prioritize 'detail' as the main message
            if "detail" in response.data:
                data["message"] = response.data["detail"]
                # If there are other fields besides detail, keep them in errors
                errors = {k: v for k, v in response.data.items() if k != "detail"}
                if errors:
                    data["errors"] = errors
            else:
                data["message"] = "Validation failed"
                data["errors"] = response.data

        # Override specific status codes only when no custom code was provided
        if not custom_code:
            if response.status_code == 404:
                data["message"] = data.get("message", "Not found")
                data["code"] = "not_found"

            if response.status_code == 401:
                data["code"] = "authentication_failed"

            if response.status_code == 403:
                data["code"] = "permission_denied"

        response.data = data

    return response
