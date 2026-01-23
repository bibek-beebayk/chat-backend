from rest_framework import serializers
from .models import Room, Message, RoomParticipant
from .models import Room, Message, RoomParticipant, SupportRoom
from accounts.serializers import UserSerializer


class SupportRoomSerializer(serializers.ModelSerializer):
    """Serializer for SupportRoom model."""
    staff = UserSerializer(read_only=True)
    
    class Meta:
        model = SupportRoom
        fields = ['id', 'name', 'staff', 'is_active']
        read_only_fields = ['id', 'is_active']



class MessageSerializer(serializers.ModelSerializer):
    """Serializer for Message model."""
    sender = UserSerializer(read_only=True)
    
    class Meta:
        model = Message
        fields = ['id', 'room', 'sender', 'content', 'attachment', 'timestamp', 'is_read']
        read_only_fields = ['id', 'timestamp']


class RoomParticipantSerializer(serializers.ModelSerializer):
    """Serializer for RoomParticipant model."""
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = RoomParticipant
        fields = ['id', 'room', 'user', 'joined_at', 'is_active']
        read_only_fields = ['id', 'joined_at']


class RoomSerializer(serializers.ModelSerializer):
    """Serializer for Room model."""
    staff_assigned = UserSerializer(read_only=True)
    client = UserSerializer(read_only=True)
    participant_count = serializers.SerializerMethodField()
    
    unread_count = serializers.IntegerField(read_only=True)
    is_staff_online = serializers.SerializerMethodField()
    
    class Meta:
        model = Room
        fields = ['id', 'name', 'staff_assigned', 'client', 'created_at', 'is_active', 'participant_count', 'unread_count', 'is_staff_online']
        read_only_fields = ['id', 'created_at']
    
    def get_participant_count(self, obj):
        return obj.participants.filter(is_active=True).count()

    def get_is_staff_online(self, obj):
        # Logic: Check if ANY staff is online for this room type.
        # This prevents "Away status" if one staff leaves but another is there.
        try:
             # Determine needed room type
             needed_type = 'all'
             if obj.client:
                 if obj.client.user_type == 'player':
                     needed_type = 'player'
                 elif obj.client.user_type == 'agent':
                     needed_type = 'agent'
             
             # Check if any ACTIVE support room exists that handles this type
             # 'all' handles everything. Specific handles specific.
             # So we look for SupportRoom where (type=needed OR type='all') AND is_active=True
             from .models import SupportRoom
             return SupportRoom.objects.filter(
                 is_active=True,
                 room_type__in=[needed_type, 'all']
             ).exists()
        except Exception as e:
            # Fallback
            return False


class RoomDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for Room model with participants and recent messages."""
    staff_assigned = UserSerializer(read_only=True)
    client = UserSerializer(read_only=True)
    participants = RoomParticipantSerializer(many=True, read_only=True)
    recent_messages = serializers.SerializerMethodField()
    
    class Meta:
        model = Room
        fields = ['id', 'name', 'staff_assigned', 'client', 'created_at', 'is_active', 'participants', 'recent_messages']
        read_only_fields = ['id', 'created_at']
    
    def get_recent_messages(self, obj):
        messages = obj.messages.all()[:50]
        return MessageSerializer(messages, many=True, context=self.context).data
