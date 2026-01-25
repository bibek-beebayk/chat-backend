# Default to dev settings if not otherwise specified
try:
    from .env import *
except ImportError:
    from .prod import *
