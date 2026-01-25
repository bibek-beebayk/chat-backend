import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import Room, Message, RoomParticipant

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
                
                if content.strip():
                    # Save message to database
                    message = await self.save_message(content)
                    
                    # Send message to room group
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'chat_message',
                            'message': content,
                            'username': self.user.username,
                            'user_id': self.user.id,
                            'message_id': message.id,
                            'timestamp': message.timestamp.isoformat(),
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
            'message_id': event['message_id'],
            'timestamp': event['timestamp'],
            'attachment': event.get('attachment'),
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
    
    @database_sync_to_async
    def check_room_exists(self):
        """Check if room exists."""
        return Room.objects.filter(id=self.room_id, status='OPEN').exists()
    
    @database_sync_to_async
    def save_message(self, content):
        """Save message to database."""
        room = Room.objects.get(id=self.room_id)
        message = Message.objects.create(
            room=room,
            sender=self.user,
            content=content
        )
        return message
    
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
