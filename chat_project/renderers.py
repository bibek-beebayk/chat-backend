from rest_framework.renderers import JSONRenderer

class StandardResponseRenderer(JSONRenderer):
    """
    Renderer that wraps successful responses in a standard format.
    {
        "status": "success",
        "data": { ... }
    }
    """
    def render(self, data, accepted_media_type=None, renderer_context=None):
        # Check if response status indicates an error
        status_code = 200
        if renderer_context and 'response' in renderer_context:
            status_code = renderer_context['response'].status_code

        # If it's already in our standard format (e.g. from exception handler), pass through
        if isinstance(data, dict) and (data.get("status") == "success" or data.get("status") == "error"):
            return super().render(data, accepted_media_type, renderer_context)

        # Handle Error Responses (that weren't caught by exception handler)
        if status_code >= 400:
            response_data = {
                "status": "error",
                "code": "error",
                "message": "An error occurred",
                "errors": data
            }
            # Try to extract a better message if possible
            if isinstance(data, dict):
                if "detail" in data:
                    response_data["message"] = data["detail"]
                    if len(data) == 1:
                        response_data["errors"] = None
                elif "non_field_errors" in data and isinstance(data["non_field_errors"], list):
                     response_data["message"] = data["non_field_errors"][0]
                else:
                    # Pick the first field error as the main message
                    # data = {"username": ["Exists"]} -> message = "Exists"
                    first_key = next(iter(data))
                    first_val = data[first_key]
                    if isinstance(first_val, list) and len(first_val) > 0:
                        response_data["message"] = first_val[0]
                    elif isinstance(first_val, str):
                        response_data["message"] = first_val
            
            return super().render(response_data, accepted_media_type, renderer_context)

        # Handle Success Responses
        response_data = {
            "status": "success",
            "data": data
        }

        return super().render(response_data, accepted_media_type, renderer_context)
