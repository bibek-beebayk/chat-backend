from rest_framework import serializers
from accounts.serializers import UserSerializer
from .models import LoginStreak, StreakRedemptionRequest, STREAK_REWARD_AMOUNT, STREAK_TARGET_DAYS


class StreakRedemptionRequestSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    reviewed_by = UserSerializer(read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = StreakRedemptionRequest
        fields = [
            'id',
            'user',
            'amount',
            'status',
            'status_label',
            'note',
            'staff_note',
            'reviewed_by',
            'reviewed_at',
            'completed_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class LoginStreakStatusSerializer(serializers.ModelSerializer):
    target_days = serializers.SerializerMethodField()
    reward_amount = serializers.SerializerMethodField()
    days_remaining = serializers.IntegerField(read_only=True)
    reward_available = serializers.BooleanField(source='is_reward_available', read_only=True)
    active_redemption_request = serializers.SerializerMethodField()

    class Meta:
        model = LoginStreak
        fields = [
            'current_streak',
            'last_login_date',
            'receivable_bonus',
            'last_awarded_at',
            'target_days',
            'reward_amount',
            'days_remaining',
            'reward_available',
            'active_redemption_request',
        ]
        read_only_fields = fields

    def get_target_days(self, obj):
        return STREAK_TARGET_DAYS

    def get_reward_amount(self, obj):
        return str(STREAK_REWARD_AMOUNT)

    def get_active_redemption_request(self, obj):
        request = (
            StreakRedemptionRequest.objects
            .filter(user=obj.user, status__in=StreakRedemptionRequest.ACTIVE_STATUSES)
            .order_by('-created_at')
            .first()
        )
        if not request:
            return None
        return StreakRedemptionRequestSerializer(request).data


class RedemptionCreateSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class RedemptionStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[
        StreakRedemptionRequest.STATUS_APPROVED,
        StreakRedemptionRequest.STATUS_COMPLETED,
        StreakRedemptionRequest.STATUS_REJECTED,
    ])
    staff_note = serializers.CharField(required=False, allow_blank=True, max_length=1000)
