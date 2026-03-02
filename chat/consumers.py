import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import Room, Message, RoomParticipant
from notifications.models import UserPresence
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for handling real-time chat.
    """
    
    async def connect(self):
        """Handle WebSocket connection."""
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'
        self.user = self.scope['user']
        
        # Check if user is authenticated
        if not self.user.is_authenticated:
            await self.close()
            return
        
        # Check if room exists
        room_exists = await self.check_room_exists()
        if not room_exists:
            await self.close()
            return
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Mark user as active in room
        await self.join_room()
        
        # Notify others that user joined
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_join',
                'username': self.user.username,
                'user_id': self.user.id
            }
        )
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, 'room_group_name'):
            # Notify others that user left
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_leave',
                    'username': self.user.username,
                    'user_id': self.user.id
                }
            )
            
            # Leave room group
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Receive message from WebSocket."""
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'chat_message')
            
            if message_type == 'chat_message':
                content = data.get('message', '')
                client_temp_id_raw = data.get('client_temp_id')
                try:
                    client_temp_id = int(client_temp_id_raw) if client_temp_id_raw is not None else None
                except (TypeError, ValueError):
                    client_temp_id = None
                reply_to_raw = data.get('reply_to')
                try:
                    reply_to_id = int(reply_to_raw) if reply_to_raw is not None else None
                except (TypeError, ValueError):
                    reply_to_id = None
                
                if content.strip():
                    # Save message to database
                    message = await self.save_message(
                        content,
                        reply_to_id=reply_to_id,
                        client_temp_id=client_temp_id,
                    )
                    
                    # Send message to room group
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'chat_message',
                            'message': content,
                            'username': self.user.username,
                            'user_id': self.user.id,
                            'user_type': self.user.user_type,
                            'message_id': message['id'],
                            'timestamp': message['timestamp'],
                            'is_read': message.get('is_read', False),
                            'client_temp_id': message.get('client_temp_id'),
                            'reply_to': message.get('reply_to'),
                            'reply_to_message': message.get('reply_to_message'),
                        }
                    )

                    # Send notification to handler and queue staff
                    targets = await self.get_notification_targets()
                    for target_id in targets:
                        if target_id != self.user.id:
                            await self.channel_layer.group_send(
                                f"user_{target_id}",
                                {
                                    'type': 'new_message_notification',
                                    'room_id': self.room_id,
                                    'room_name': f"Chat {self.room_id}", # Or fetch name in helper if needed, simplified for speed
                                    'message_id': message['id'],
                                    'sender_username': self.user.username
                                }
                            )
            
            elif message_type == 'typing':
                 await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'user_typing',
                        'username': self.user.username,
                        'user_id': self.user.id
                    }
                 )
            
        except json.JSONDecodeError:
            pass
    
    async def chat_message(self, event):
        """Send chat message to WebSocket."""
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message'],
            'username': event['username'],
            'user_id': event['user_id'],
            'user_type': event.get('user_type', 'client'),
            'message_id': event['message_id'],
            'timestamp': event['timestamp'],
            'is_read': event.get('is_read', False),
            'client_temp_id': event.get('client_temp_id'),
            'attachment': event.get('attachment'),
            'reply_to': event.get('reply_to'),
            'reply_to_message': event.get('reply_to_message'),
        }))
    
    async def user_join(self, event):
        """Send user join notification to WebSocket."""
        await self.send(text_data=json.dumps({
            'type': 'user_join',
            'username': event['username'],
            'user_id': event['user_id'],
        }))
    
    async def user_leave(self, event):
        """Send user leave notification to WebSocket."""
        await self.send(text_data=json.dumps({
            'type': 'user_leave',
            'username': event['username'],
            'user_id': event['user_id'],
        }))

    async def user_typing(self, event):
        """Send user typing notification."""
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'username': event['username'],
            'user_id': event['user_id']
        }))

    async def chat_message_update(self, event):
        """Send message update notification."""
        await self.send(text_data=json.dumps({
            'type': 'chat_message_update',
            'message_id': event['id'],
            'message': event['content'],
            'is_edited': event['is_edited'],
            'edited_at': event['edited_at']
        }))

    async def chat_message_delete(self, event):
        """Send message delete notification."""
        await self.send(text_data=json.dumps({
            'type': 'chat_message_delete',
            'message_id': event['id'],
            'is_deleted': event['is_deleted']
        }))
        
    async def chat_message_pin(self, event):
        """Send message pin notification."""
        await self.send(text_data=json.dumps({
            'type': 'chat_message_pin',
            'message_id': event['id'],
            'is_pinned': event['is_pinned']
        }))

    async def chat_message_read(self, event):
        """Send read receipt update."""
        await self.send(text_data=json.dumps({
            'type': 'chat_message_read',
            'message_ids': event.get('message_ids', []),
            'reader_id': event.get('reader_id'),
        }))
    
    @database_sync_to_async
    def check_room_exists(self):
        """Check if room exists and belongs to the caller's test scope."""
        try:
            room = Room.objects.select_related('queue', 'client').get(
                id=self.room_id,
                status='OPEN',
            )
        except Room.DoesNotExist:
            return False

        user_is_test = bool(getattr(self.user, 'is_test_user', False))
        if bool(room.is_test_room) != user_is_test:
            return False

        if self.user.user_type == 'staff':
            return (
                room.current_handler_id == self.user.id
                or (room.queue_id is not None and self.user.active_support_rooms.filter(id=room.queue_id).exists())
                or room.participants.filter(user=self.user, is_active=True).exists()
            )

        return room.client_id == self.user.id
    
    @database_sync_to_async
    def save_message(self, content, reply_to_id=None, client_temp_id=None):
        """Save message to database."""
        room = Room.objects.get(id=self.room_id)
        reply_to_message = None
        if reply_to_id:
            reply_to_message = Message.objects.filter(
                id=reply_to_id,
                room=room,
            ).first()
        message = Message.objects.create(
            room=room,
            sender=self.user,
            content=content,
            reply_to=reply_to_message,
        )
        reply_payload = None
        if reply_to_message:
            reply_payload = {
                'id': reply_to_message.id,
                'content': reply_to_message.content,
                'sender_username': reply_to_message.sender.username,
                'sender': {
                    'id': reply_to_message.sender.id,
                    'username': reply_to_message.sender.username,
                    'user_type': reply_to_message.sender.user_type,
                },
            }

        return {
            'id': message.id,
            'timestamp': message.timestamp.isoformat(),
            'is_read': message.is_read,
            'client_temp_id': client_temp_id,
            'reply_to': reply_to_message.id if reply_to_message else None,
            'reply_to_message': reply_payload,
        }
    
    @database_sync_to_async
    def join_room(self):
        """Mark user as active participant in room."""
        room = Room.objects.get(id=self.room_id)
        participant, created = RoomParticipant.objects.get_or_create(
            room=room,
            user=self.user
        )
        participant.is_active = True
        participant.save()

    @database_sync_to_async
    def get_room(self):
        """Get room instance."""
        try:
             return Room.objects.get(id=self.room_id)
        except Room.DoesNotExist:
             return None

    @database_sync_to_async
    def get_notification_targets(self):
        """Get list of user IDs to notify (handler + queue staff)."""
        try:
             room = Room.objects.select_related('current_handler', 'queue', 'queue__staff', 'client').get(id=self.room_id)
             targets = set()
             scope_is_test = bool(room.is_test_room)
             
             # Logic similar to signals.py: Notify everyone else involved
             
             # 1. Client
             if room.client and bool(getattr(room.client, 'is_test_user', False)) == scope_is_test:
                 targets.add(room.client.id)
                 
             # 2. Handler
             if room.current_handler and bool(getattr(room.current_handler, 'is_test_user', False)) == scope_is_test:
                 targets.add(room.current_handler.id)
                 
             # 3. Queue Staff (Optional, maybe only if no handler?)
             if room.queue and room.queue.staff and bool(getattr(room.queue.staff, 'is_test_user', False)) == scope_is_test:
                 targets.add(room.queue.staff.id)

             # 4. Room Participants (e.g. for group chats or backup)
             # This is crucial if logic above misses someone
             participants = RoomParticipant.objects.filter(
                 room=room,
                 is_active=True,
                 user__is_test_user=scope_is_test,
             ).values_list('user_id', flat=True)
             for uid in participants:
                 targets.add(uid)

             return list(targets)
        except Room.DoesNotExist:
             return []

class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for global user notifications and presence tracking.
    """
    async def connect(self):
        self.user = self.scope['user']
        print(f"DEBUG: NotificationConsumer connect for user: {self.user}")
        if not self.user.is_authenticated:
            print("DEBUG: NotificationConsumer rejecting unauthenticated user")
            await self.close()
            return

        self.group_name = f"user_{self.user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Update presence to ONLINE
        await self.update_presence('ONLINE')

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
             await self.channel_layer.group_discard(self.group_name, self.channel_name)
        
        # Update presence to OFFLINE
        await self.update_presence('OFFLINE')

    async def receive(self, text_data):
        """Handle heartbeat and other control messages."""
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')
            
            if msg_type == 'heartbeat':
                await self.update_presence('ONLINE')
                
        except json.JSONDecodeError:
            pass

    async def new_message_notification(self, event):
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def update_presence(self, status):
        """Update user presence status."""
        if not self.user.is_authenticated:
            return

        presence, _ = UserPresence.objects.get_or_create(user=self.user)
        presence.status = status
        presence.socket_id = self.channel_name
        presence.last_seen = timezone.now()
        presence.save()
