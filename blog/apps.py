from django.apps import AppConfig


class BlogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'blog'

    def ready(self):
        # Register blog-specific signals (on-demand frontend revalidation).
        from . import signals  # noqa: F401

