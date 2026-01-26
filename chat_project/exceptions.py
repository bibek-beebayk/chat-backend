from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    """
    Custom exception handler that standardizes error responses.
    Response format:
    {
        "status": "error",
        "code": "error_code_string",
        "message": "Human readable summary",
        "errors": { "field": ["detail"] },
        "path": "/api/..."
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
        data["code"] = exc.__class__.__name__
        
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
        
        # Override specific status messages if needed
        if response.status_code == 404:
            data["message"] = data.get("message", "Not found")
            data["code"] = "not_found"
            
        if response.status_code == 401:
            data["code"] = "authentication_failed"
            
        if response.status_code == 403:
            data["code"] = "permission_denied"

        response.data = data
    
    return response
