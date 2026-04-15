from rest_framework import serializers
from .models import (
    Room,
    Message,
    RoomParticipant,
    SupportRoom,
    AgentQuickReply,
    ChatInternalNote,
    GroupJoinRequest,
)
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
            'is_broadcast',
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
    group_admin = UserSerializer(read_only=True)
    participant_count = serializers.SerializerMethodField()
    group_member_count = serializers.SerializerMethodField()
    user_is_group_admin = serializers.SerializerMethodField()

    unread_count = serializers.IntegerField(read_only=True)
    is_staff_online = serializers.SerializerMethodField()

    queue = serializers.PrimaryKeyRelatedField(read_only=True)
    queue_name = serializers.CharField(source='queue.name', read_only=True)
    queue_type = serializers.CharField(source='queue.room_type', read_only=True)
    can_switch_station = serializers.SerializerMethodField()
    room_type = serializers.CharField(read_only=True)
    counterpart = serializers.SerializerMethodField()
    last_activity = serializers.DateTimeField(read_only=True)
    last_message_sender_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Room
        fields = [
            'id', 'name', 'room_type', 'counterpart', 'current_handler', 'client',
            'group_admin', 'group_description', 'group_member_count', 'user_is_group_admin',
            'created_at', 'status', 'participant_count', 'unread_count', 'is_staff_online',
            'queue', 'queue_name', 'queue_type', 'can_switch_station', 'last_activity',
            'last_message_sender_id'
        ]
        read_only_fields = ['id', 'created_at']

    def get_participant_count(self, obj):
        return obj.participants.filter(is_active=True).count()

    def get_group_member_count(self, obj):
        if obj.room_type != 'group':
            return 0
        return obj.participants.filter(is_active=True).count()

    def get_user_is_group_admin(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        return obj.room_type == 'group' and obj.group_admin_id == user.id

    def get_is_staff_online(self, obj):
        if obj.room_type in ('direct_agent', 'group'):
            return False
        try:
            from .models import SupportRoom
            if obj.queue:
                return SupportRoom.objects.filter(
                    room_type=obj.queue.room_type,
                    is_active=True,
                    staff__isnull=False
                ).exists()

            needed_type = 'all'
            if obj.client:
                if obj.client.user_type == 'player':
                    needed_type = 'player'
                elif obj.client.user_type == 'agent':
                    needed_type = 'agent'

            return SupportRoom.objects.filter(
                room_type__in=[needed_type, 'all'],
                is_active=True,
                staff__isnull=False
            ).exists()
        except Exception:
            return False

    def get_can_switch_station(self, obj):
        if obj.room_type != 'support':
            return False
        if not obj.queue:
            return False

        from .models import SupportRoom
        return SupportRoom.objects.filter(
            room_type=obj.queue.room_type,
            is_active=True,
            staff__isnull=False
        ).exclude(id=obj.queue.id).exists()

    def get_counterpart(self, obj):
        if obj.room_type != 'direct_agent':
            return None
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return None
        target = None
        if obj.direct_player_id == user.id:
            target = obj.direct_agent
        elif obj.direct_agent_id == user.id:
            target = obj.direct_player
        if target is None:
            return None
        return UserSerializer(target).data


class RoomDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for Room model with participants and recent messages."""
    current_handler = UserSerializer(read_only=True)
    client = UserSerializer(read_only=True)
    group_admin = UserSerializer(read_only=True)
    participants = RoomParticipantSerializer(many=True, read_only=True)
    recent_messages = serializers.SerializerMethodField()

    queue = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Room
        fields = [
            'id', 'name', 'room_type', 'client', 'group_admin', 'group_description',
            'current_handler', 'status', 'created_at', 'participants', 'recent_messages', 'queue'
        ]
        read_only_fields = ['id', 'created_at']

    def get_recent_messages(self, obj):
        messages = obj.messages.all()[:50]
        return MessageSerializer(messages, many=True, context=self.context).data


class AgentQuickReplySerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentQuickReply
        fields = ['id', 'title', 'content', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class ChatInternalNoteSerializer(serializers.ModelSerializer):
    updated_by = UserSerializer(read_only=True)

    class Meta:
        model = ChatInternalNote
        fields = ['room', 'content', 'updated_by', 'updated_at']
        read_only_fields = ['updated_by', 'updated_at']


class GroupJoinRequestSerializer(serializers.ModelSerializer):
    player = UserSerializer(read_only=True)
    room = RoomSerializer(read_only=True)

    class Meta:
        model = GroupJoinRequest
        fields = ['id', 'room', 'player', 'status', 'requested_at', 'reviewed_at']
        read_only_fields = ['id', 'status', 'requested_at', 'reviewed_at']
