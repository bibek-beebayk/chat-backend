from .models import Notification


def create_notification(user, title, body, link=''):
    """
    Generic in-app notification creator. Existing callers (e.g. the chat
    push dispatcher) create Notification rows inline; this is the shared
    entry point for anything else that needs to notify a user (e.g. XP
    rank-ups) without duplicating the model call.
    """
    return Notification.objects.create(user=user, title=title, body=body, link=link)
