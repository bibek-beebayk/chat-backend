from django.utils import timezone
from .models import UserPresence, MessageDelivery, PushToken, Notification
from .fcm import send_push_notification
from chat.models import Message
import logging

logger = logging.getLogger(__name__)

class MessageDispatcher:
    """
    Core Logic for routing messages based on User Presence.
    """
    
    @staticmethod
    def dispatch(message, target_user):
        """
        Main entry point. Decide how to deliver the message to target_user.
        """
        # 1. Check Presence
        try:
            presence = target_user.presence
            status = presence.status
            # Check if last_seen is recent (e.g., within 60 seconds) even if status is ONLINE
            # to detect unclean disconnects.
            time_since_seen = (timezone.now() - presence.last_seen).total_seconds()
            if status == 'ONLINE' and time_since_seen > 60:
                # Downgrade to IDLE or OFFLINE
                status = 'IDLE' # or OFFLINE
                # Update DB? Maybe better to just treat as IDLE for delivery
                
        except UserPresence.DoesNotExist:
            status = 'OFFLINE'

        logger.info(f"Dispatching msg {message.id} to {target_user.username} (Status: {status})")

        # 2. Delivery Logic
        # IF ONLINE → WebSocket only (Already handled by Consumers usually, but we should verify/log)
        # IF IDLE → WebSocket + Silent Push (or regular Push if very idle)
        # IF OFFLINE → Push Notification
        # IF DISCONNECTED → Push It
        
        # We record the PRIMARY attempt
        
        if status == 'ONLINE':
            # Assume WebSocket delivery success, but log it
            MessageDelivery.objects.create(
                message=message,
                user=target_user,
                channel='ws',
                status='delivered' # Optimistic
            )
            # Maybe send a "Silent" push or just update badge?
            # For now, relying on WS.

        elif status in ['IDLE', 'OFFLINE', 'DISCONNECTED']:
            # Send Push
            MessageDispatcher._send_push(message, target_user)
            
            # Record WS failure/skip
            MessageDelivery.objects.create(
                message=message,
                user=target_user,
                channel='ws',
                status='failed',
                error_message=f"User is {status}"
            )
            
    
    @staticmethod
    def _send_push(message, user):
        """
        Send Push Notification via FCM.
        """
        tokens = PushToken.objects.filter(user=user, is_active=True).values_list('fcm_token', flat=True)
        token_list = list(tokens)
        
        if not token_list:
            logger.info(f"No push tokens for {user.username}. Falling back to Email.")
            MessageDispatcher._schedule_email(message, user)
            return

        # Prepare payload
        sender_name = "Hi-Rollin" if message.sender.user_type == 'staff' else message.sender.username
        title = f"New message from {sender_name}"
        body = message.content[:100] # Truncate check
        link = f"/chat/{message.room.id}" # Deep link
        
        # Create In-App Notification record
        Notification.objects.create(
            user=user,
            title=title,
            body=body,
            link=link
        )

        # Create Delivery Record
        delivery = MessageDelivery.objects.create(
            message=message,
            user=user,
            channel='push',
            status='sent'
        )

        try:
            success_count = send_push_notification(token_list, title, body, link)
            if success_count > 0:
                delivery.status = 'delivered'
                delivery.save()
            else:
                delivery.status = 'failed'
                delivery.error_message = "FCM returned 0 success"
                delivery.save()
                # Fallback
                MessageDispatcher._schedule_email(message, user)
                
        except Exception as e:
            delivery.status = 'failed'
            delivery.error_message = str(e)
            delivery.save()
            MessageDispatcher._schedule_email(message, user)

    @staticmethod
    def _schedule_email(message, user):
        """
        Fallback to Email.
        """
        # Create Delivery Record
        delivery = MessageDelivery.objects.create(
            message=message,
            user=user,
            channel='email',
            status='pending' 
        )
        
        # Check if user has been inactive for at least 5 minutes
        # If they just went offline (e.g. < 5 mins ago), we do NOT send immediately.
        # We leave it as 'pending' to be picked up by a potential background job or explicit retry.
        # Given current constraints without background workers, we simply enforce the policy:
        # If offline < 5 mins, we SKIP sending email now.
        
        try:
            presence = user.presence
            time_since_seen = (timezone.now() - presence.last_seen).total_seconds()
            if time_since_seen < 300: # 5 minutes
                logger.info(f"Skipping email for {user.username}: Only offline for {int(time_since_seen)}s")
                delivery.status = 'skipped_recent'
                delivery.save()
                return
        except UserPresence.DoesNotExist:
            # If no presence record, assume long offline
            pass
        
        # Check rate limits or user preferences?
        # Send Email
        from chat_project.utils import send_zeptomail
        
        try:
             # Basic email content
             subject = "You have a new message on Rollin Community"
             body = f"Hello {user.username},<br><br>You have a new message from {message.sender.username}.<br><br>Content: {message.content[:50]}...<br><a href='https://community.hrlzone.com/chat'>Go to Chat</a>"
             
             send_zeptomail(user.email, subject, f"<html><body>{body}</body></html>")
             
             delivery.status = 'sent'
             delivery.save()
             
        except Exception as e:
             delivery.status = 'failed'
             delivery.error_message = str(e)
             delivery.save()
