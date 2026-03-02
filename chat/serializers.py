from rest_framework import serializers
from .models import Room, Message, RoomParticipant
from .models import Room, Message, RoomParticipant, SupportRoom
from accounts.serializers import UserSerializer


class SupportRoomSerializer(serializers.ModelSerializer):
    """Serializer for SupportRoom model."""
    staff = UserSerializer(read_only=True)
    
    class Meta:
        model = SupportRoom
        fields = ['id', 'name', 'staff', 'is_active', 'room_type']
        read_only_fields = ['id', 'is_active', 'room_type']



class MessageSerializer(serializers.ModelSerializer):
    """Serializer for Message model."""
    sender = UserSerializer(read_only=True)
    reply_to_message = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id',
            'room',
            'sender',
            'content',
            'attachment',
            'reply_to',
            'reply_to_message',
            'timestamp',
            'is_read',
            'is_edited',
            'edited_at',
            'is_pinned',
            'is_deleted',
        ]
        read_only_fields = ['id', 'timestamp']

    def get_reply_to_message(self, obj):
        if not obj.reply_to_id or not obj.reply_to:
            return None

        return {
            'id': obj.reply_to.id,
            'content': obj.reply_to.content,
            'sender_username': obj.reply_to.sender.username,
            'sender': {
                'id': obj.reply_to.sender.id,
                'username': obj.reply_to.sender.username,
                'user_type': obj.reply_to.sender.user_type,
            },
            'attachment': obj.reply_to.attachment.url if obj.reply_to.attachment else None,
        }


class RoomParticipantSerializer(serializers.ModelSerializer):
    """Serializer for RoomParticipant model."""
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = RoomParticipant
        fields = ['id', 'room', 'user', 'joined_at', 'is_active']
        read_only_fields = ['id', 'joined_at']


class RoomSerializer(serializers.ModelSerializer):
    """Serializer for Room model."""
    current_handler = UserSerializer(read_only=True)
    client = UserSerializer(read_only=True)
    participant_count = serializers.SerializerMethodField()
    
    unread_count = serializers.IntegerField(read_only=True)
    is_staff_online = serializers.SerializerMethodField()
    
    queue = serializers.PrimaryKeyRelatedField(read_only=True)
    queue_name = serializers.CharField(source='queue.name', read_only=True)
    queue_type = serializers.CharField(source='queue.room_type', read_only=True)
    can_switch_station = serializers.SerializerMethodField()
    
    class Meta:
        model = Room
        fields = ['id', 'name', 'current_handler', 'client', 'created_at', 'status', 'participant_count', 'unread_count', 'is_staff_online', 'queue', 'queue_name', 'queue_type', 'can_switch_station']
        read_only_fields = ['id', 'created_at']
    
    def get_participant_count(self, obj):
        return obj.participants.filter(is_active=True).count()

    def get_is_staff_online(self, obj):
        # Logic: Check if ANY staff is online for this room type.
        try:
            from .models import SupportRoom
            if obj.queue:
                # Check if anyone is handling this type of queue (load balancing)
                # Or just check if THIS queue is active? 
                # Let's say: Is there ANY active queue of this type?
                return SupportRoom.objects.filter(
                    room_type=obj.queue.room_type,
                    is_active=True,
                    staff__isnull=False
                ).exists()
                
            # Fallback if no queue assigned yet (e.g. new room)
            needed_type = 'all'
            if obj.client:
                 if obj.client.user_type == 'player': needed_type = 'player'
                 elif obj.client.user_type == 'agent': needed_type = 'agent'
            
            return SupportRoom.objects.filter(
                 room_type__in=[needed_type, 'all'],
                 is_active=True,
                 staff__isnull=False
            ).exists()
        except:
            return False

    def get_can_switch_station(self, obj):
        if not obj.queue:
            return False
            
        # Check if there are OTHER active stations of the same type
        from .models import SupportRoom
        return SupportRoom.objects.filter(
            room_type=obj.queue.room_type,
            is_active=True,
            staff__isnull=False
        ).exclude(id=obj.queue.id).exists()


class RoomDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for Room model with participants and recent messages."""
    current_handler = UserSerializer(read_only=True)
    client = UserSerializer(read_only=True)
    participants = RoomParticipantSerializer(many=True, read_only=True)
    recent_messages = serializers.SerializerMethodField()
    
    queue = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = Room
        fields = ['id', 'name', 'client', 'current_handler', 'status', 'created_at', 'unread_count', 'messages', 'queue']
        read_only_fields = ['id', 'created_at', 'messages']
    
    def get_recent_messages(self, obj):
        messages = obj.messages.all()[:50]
        return MessageSerializer(messages, many=True, context=self.context).data
