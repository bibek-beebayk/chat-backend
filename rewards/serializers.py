from rest_framework import serializers
from accounts.serializers import UserSerializer
from .models import (
    LoginStreak,
    LoginStreakEntry,
    StreakRedemptionRequest,
    STREAK_REWARD_AMOUNT,
    STREAK_TARGET_DAYS,
)


class LoginStreakEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginStreakEntry
        fields = [
            'id',
            'login_date',
            'created_at',
        ]
        read_only_fields = fields


class StreakRedemptionRequestSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    reviewed_by = UserSerializer(read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    verification_entries = serializers.SerializerMethodField()
    verification_summary = serializers.SerializerMethodField()

    class Meta:
        model = StreakRedemptionRequest
        fields = [
            'id',
            'user',
            'amount',
            'hi_rollin_username',
            'status',
            'status_label',
            'note',
            'staff_note',
            'reviewed_by',
            'reviewed_at',
            'completed_at',
            'created_at',
            'updated_at',
            'verification_entries',
            'verification_summary',
        ]
        read_only_fields = fields

    def get_verification_entries(self, obj):
        requested_date = obj.created_at.date()
        entries = (
            LoginStreakEntry.objects
            .filter(user=obj.user, login_date__lte=requested_date)
            .order_by('-login_date', '-created_at')[:STREAK_TARGET_DAYS]
        )
        return LoginStreakEntrySerializer(reversed(list(entries)), many=True).data

    def get_verification_summary(self, obj):
        entries = list(
            LoginStreakEntry.objects
            .filter(user=obj.user, login_date__lte=obj.created_at.date())
            .order_by('-login_date', '-created_at')[:STREAK_TARGET_DAYS]
        )
        entries.reverse()
        dates = [entry.login_date for entry in entries]
        is_consecutive = len(dates) >= STREAK_TARGET_DAYS and all(
            (dates[index] - dates[index - 1]).days == 1
            for index in range(1, len(dates))
        )
        return {
            'target_days': STREAK_TARGET_DAYS,
            'record_count': len(entries),
            'is_consecutive': is_consecutive,
            'start_date': dates[0] if dates else None,
            'end_date': dates[-1] if dates else None,
        }


class LoginStreakStatusSerializer(serializers.ModelSerializer):
    target_days = serializers.SerializerMethodField()
    reward_amount = serializers.SerializerMethodField()
    days_remaining = serializers.IntegerField(read_only=True)
    reward_available = serializers.BooleanField(source='is_reward_available', read_only=True)
    active_redemption_request = serializers.SerializerMethodField()
    last_redemption_request = serializers.SerializerMethodField()

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
            'last_redemption_request',
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

    def get_last_redemption_request(self, obj):
        request = (
            StreakRedemptionRequest.objects
            .filter(user=obj.user)
            .order_by('-created_at')
            .first()
        )
        if not request:
            return None
        return StreakRedemptionRequestSerializer(request).data


class RedemptionCreateSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    hi_rollin_username = serializers.CharField(required=True, max_length=100)

    def validate_hi_rollin_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Hi-Rollin account username is required.')
        return value


class RedemptionStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[
        StreakRedemptionRequest.STATUS_APPROVED,
        StreakRedemptionRequest.STATUS_COMPLETED,
        StreakRedemptionRequest.STATUS_REJECTED,
    ])
    staff_note = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate(self, attrs):
        status = attrs.get('status')
        staff_note = (attrs.get('staff_note') or '').strip()
        if status == StreakRedemptionRequest.STATUS_REJECTED and not staff_note:
            raise serializers.ValidationError({'staff_note': 'Rejection reason is required.'})
        attrs['staff_note'] = staff_note
        return attrs
