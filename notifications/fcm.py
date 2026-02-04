import firebase_admin
from firebase_admin import messaging, credentials
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

_is_initialized = False

def initialize_firebase():
    global _is_initialized
    if _is_initialized:
        return

    try:
        if not firebase_admin._apps:
             # Use the service account file we just saved
             cred = credentials.Certificate(str(settings.BASE_DIR / 'serviceAccountKey.json'))
             firebase_admin.initialize_app(cred)
             _is_initialized = True
        else:
             _is_initialized = True
             
    except Exception as e:
        logger.warning(f"Failed to initialize Firebase Admin: {e}")

def send_push_notification(user_tokens, title, body, link=None):
    """
    Send push notification to a list of tokens.
    """
    initialize_firebase()
    
    if not _is_initialized:
        logger.error("Firebase not initialized, cannot send push")
        return 0

    valid_tokens = []
    messages = []
    
    base_url = "https://betunnel.worldstories.net" # Hardcoded for now as per user env, or fetch from settings
    
    for token in user_tokens:
        # Construct absolute URL
        relative_link = link or '/'
        if not relative_link.startswith('http'):
             full_link = f"{base_url}{relative_link}" if relative_link.startswith('/') else f"{base_url}/{relative_link}"
        else:
             full_link = relative_link

        # Send both Notification and Data for maximum compatibility
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            webpush=messaging.WebpushConfig(
                fcm_options=messaging.WebpushFCMOptions(
                    link=full_link
                ),
                notification=messaging.WebpushNotification(
                    icon='/logo.png'
                )
            ),
            token=token,
            data={
                'link': full_link,
                'title': title,
                'body': body,
                'icon': '/logo.png'
            }
        )
        messages.append(message)

    if not messages:
        return 0

    try:
        # Batch send
        batch_response = messaging.send_each(messages)
        logger.info(f"FCM Send Result: {batch_response.success_count} success, {batch_response.failure_count} failures")
        if batch_response.failure_count > 0:
             for idx, resp in enumerate(batch_response.responses):
                 if not resp.success:
                     logger.warning(f"FCM Failure {idx}: {resp.exception}")
        return batch_response.success_count
    except Exception as e:
        logger.error(f"Error sending FCM messages: {e}")
        return 0
