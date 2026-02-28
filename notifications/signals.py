from django.db.models.signals import post_save
from django.dispatch import receiver
from chat.models import Message, RoomParticipant
from .dispatcher import MessageDispatcher
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Message)
def handle_new_message(sender, instance, created, **kwargs):
    """
    Trigger delivery logic when a new message is created.
    """
    if created:
        logger.info(f"New message {instance.id} created in Room {instance.room.id}")
        
        # Identify targets
        # The message is sent BY instance.sender
        # It should be sent TO all other participants in the room
        # Or specifically the 'recipient' if it's 1-on-1.
        
        # Logic:
        # If Room has client/handler structure:
        # - If Client sent it -> Notify Handler (and Queue if no handler)
        # - If Handler sent it -> Notify Client
        
        room = instance.room
        sender_id = instance.sender.id
        scope_is_test = bool(room.is_test_room)
        
        # Get all participants
        # We can use RoomParticipant model or Room fields
        
        targets = []
        
        # Check explicit Room fields first (One-to-One logic)
        if room.client and room.client.id != sender_id and bool(getattr(room.client, 'is_test_user', False)) == scope_is_test:
            targets.append(room.client)
            
        if room.current_handler and room.current_handler.id != sender_id and bool(getattr(room.current_handler, 'is_test_user', False)) == scope_is_test:
            targets.append(room.current_handler)
            
        # Also check Queue staff if no handler?
        # Maybe not for now, to avoid spamming the generic queue user.
        
        # Also check RoomParticipant for group chats (if any)
        participants = RoomParticipant.objects.filter(
            room=room,
            is_active=True,
            user__is_test_user=scope_is_test,
        ).select_related('user')
        for p in participants:
            if p.user.id != sender_id and p.user not in targets:
                targets.append(p.user)
                
        # Dispatch to each target non-blockingly
        for target in targets:
             MessageDispatcher.dispatch_async(instance, target)
