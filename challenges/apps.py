from django.apps import AppConfig


class ChallengesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'challenges'
    # Shown as the admin sidebar section header - this app has no tables of
    # its own (see models.py's proxy models), it exists purely to give
    # Daily/Weekly/Special Challenges their own grouped, focused admin UI
    # separate from the general "Xp" section's full XPAction list.
    verbose_name = 'Challenges'
