from django.contrib.auth import get_user_model
from rest_framework import serializers

from accounts.serializers import UserSerializer
from chat_project.url_utils import build_public_absolute_uri

from .models import UserConnection, UserOnboardingState

User = get_user_model()


class UserOnboardingStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserOnboardingState
        fields = [
            'has_seen_agent_suggestions',
            'has_seen_player_suggestions',
            'has_completed_social_onboarding',
            'completed_at',
            'onboarding_version',
            'updated_at',
        ]
        read_only_fields = ['completed_at', 'updated_at']


class UserConnectionSerializer(serializers.ModelSerializer):
    requester = UserSerializer(read_only=True)
    receiver = UserSerializer(read_only=True)

    class Meta:
        model = UserConnection
        fields = [
            'id',
            'requester',
            'receiver',
            'connection_type',
            'status',
            'initiated_from_onboarding',
            'accepted_at',
            'rejected_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class SuggestedUserSerializer(serializers.ModelSerializer):
    headline = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()
    profile_thumbnail = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'user_type',
            'is_verified',
            'profile_picture',
            'profile_thumbnail',
            'avatar',
            'agent_availability',
            'agent_status_note',
            'headline',
        ]

    def get_profile_picture(self, obj):
        if not obj.profile_picture:
            return None
        request = self.context.get('request')
        url = obj.profile_picture.url
        return build_public_absolute_uri(request, url)

    def get_profile_thumbnail(self, obj):
        if not obj.profile_thumbnail:
            return None
        request = self.context.get('request')
        url = obj.profile_thumbnail.url
        return build_public_absolute_uri(request, url)

    def get_avatar(self, obj):
        return self.get_profile_thumbnail(obj) or self.get_profile_picture(obj)

    def get_headline(self, obj):
        if obj.user_type == 'agent':
            if obj.agent_status_note:
                return obj.agent_status_note
            return 'Verified agent' if obj.is_verified else 'Agent'
        return 'Verified player' if obj.is_verified else 'Player'


class ConnectionSearchUserSerializer(SuggestedUserSerializer):
    is_connected = serializers.SerializerMethodField()
    connection_status = serializers.SerializerMethodField()

    class Meta(SuggestedUserSerializer.Meta):
        fields = SuggestedUserSerializer.Meta.fields + [
            'is_connected',
            'connection_status',
        ]

    def get_is_connected(self, obj):
        connected_ids = self.context.get('connected_ids', set())
        return obj.id in connected_ids

    def get_connection_status(self, obj):
        status_map = self.context.get('connection_status_map', {})
        return status_map.get(obj.id, 'none')


class PublicUserProfileSerializer(serializers.ModelSerializer):
    connection_status = serializers.SerializerMethodField()
    can_connect = serializers.SerializerMethodField()
    can_disconnect = serializers.SerializerMethodField()
    can_chat = serializers.SerializerMethodField()
    primary_action = serializers.SerializerMethodField()
    secondary_action = serializers.SerializerMethodField()
    joined_at = serializers.DateTimeField(source='date_joined', read_only=True)
    headline = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()
    profile_thumbnail = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'user_type',
            'is_verified',
            'profile_picture',
            'profile_thumbnail',
            'avatar',
            'agent_availability',
            'agent_status_note',
            'first_name',
            'last_name',
            'joined_at',
            'headline',
            'connection_status',
            'can_connect',
            'can_disconnect',
            'can_chat',
            'primary_action',
            'secondary_action',
        ]

    def _context_value(self, key, default=None):
        return self.context.get(key, default)

    def get_profile_picture(self, obj):
        if not obj.profile_picture:
            return None
        request = self.context.get('request')
        url = obj.profile_picture.url
        return build_public_absolute_uri(request, url)

    def get_profile_thumbnail(self, obj):
        if not obj.profile_thumbnail:
            return None
        request = self.context.get('request')
        url = obj.profile_thumbnail.url
        return build_public_absolute_uri(request, url)

    def get_avatar(self, obj):
        return self.get_profile_thumbnail(obj) or self.get_profile_picture(obj)

    def get_headline(self, obj):
        if obj.user_type == 'agent':
            return obj.agent_status_note or ('Verified agent' if obj.is_verified else 'Agent')
        return 'Verified player' if obj.is_verified else 'Player'

    def get_connection_status(self, obj):
        return self._context_value('connection_status', 'none')

    def get_can_connect(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        if request.user.id == obj.id:
            return False
        return self._context_value('can_connect', False)

    def get_can_disconnect(self, obj):
        return self._context_value('can_disconnect', False)

    def get_can_chat(self, obj):
        return self._context_value('can_chat', False)

    def get_primary_action(self, obj):
        return self._context_value('primary_action')

    def get_secondary_action(self, obj):
        return self._context_value('secondary_action')

