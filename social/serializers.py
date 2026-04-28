from django.contrib.auth import get_user_model
from rest_framework import serializers

from accounts.serializers import UserSerializer

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

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'user_type',
            'is_verified',
            'profile_picture',
            'avatar',
            'agent_availability',
            'agent_status_note',
            'headline',
        ]

    def get_headline(self, obj):
        if obj.user_type == 'agent':
            if obj.agent_status_note:
                return obj.agent_status_note
            return 'Verified agent' if obj.is_verified else 'Agent'
        return 'Verified player' if obj.is_verified else 'Player'


class PublicUserProfileSerializer(serializers.ModelSerializer):
    connection_status = serializers.SerializerMethodField()
    can_connect = serializers.SerializerMethodField()
    can_chat = serializers.SerializerMethodField()
    primary_action = serializers.SerializerMethodField()
    secondary_action = serializers.SerializerMethodField()
    joined_at = serializers.DateTimeField(source='date_joined', read_only=True)
    headline = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'user_type',
            'is_verified',
            'profile_picture',
            'avatar',
            'agent_availability',
            'agent_status_note',
            'first_name',
            'last_name',
            'joined_at',
            'headline',
            'connection_status',
            'can_connect',
            'can_chat',
            'primary_action',
            'secondary_action',
        ]

    def _context_value(self, key, default=None):
        return self.context.get(key, default)

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

    def get_can_chat(self, obj):
        return self._context_value('can_chat', False)

    def get_primary_action(self, obj):
        return self._context_value('primary_action')

    def get_secondary_action(self, obj):
        return self._context_value('secondary_action')

