from decimal import Decimal
from datetime import timezone as datetime_timezone
import hmac
import hashlib

from django.conf import settings
from django.utils import timezone
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


class ScratchRedemptionCreateSerializer(serializers.Serializer):
    EXTERNAL_SOURCE_CHOICES = {'scratch', 'win'}

    source = serializers.CharField(max_length=120)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    reward_id = serializers.CharField(max_length=160)
    expires = serializers.IntegerField()
    signature = serializers.CharField(max_length=256)
    hi_rollin_username = serializers.CharField(max_length=100)
    query_params = serializers.JSONField(required=False)

    def validate_source(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Source is required.')
        if value not in self.EXTERNAL_SOURCE_CHOICES:
            raise serializers.ValidationError('Unsupported reward source.')
        return value

    def validate_reward_id(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Reward id is required.')
        return value

    def validate_signature(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Signature is required.')
        return value

    def validate_hi_rollin_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Hi-Rollin account username is required.')
        return value

    def validate_query_params(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('Query params must be an object.')
        return value

    def validate(self, attrs):
        secret = getattr(settings, 'SCRATCH_REWARD_SIGNING_SECRET', '')
        if not secret:
            raise serializers.ValidationError('Reward verification is not configured.')

        expires_at = timezone.datetime.fromtimestamp(attrs['expires'], tz=datetime_timezone.utc)
        if expires_at <= timezone.now():
            raise serializers.ValidationError('This reward link has expired.')

        amount_text = str(self.initial_data.get('amount', '')).strip()
        message = f"{attrs['source']}|{amount_text}|{attrs['reward_id']}|{attrs['expires']}"
        expected = hmac.new(
            secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, attrs['signature']):
            raise serializers.ValidationError('Invalid reward signature.')

        attrs['expires_at'] = expires_at
        attrs['signed_message'] = message
        return attrs


class StreakRedemptionRequestSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    reviewed_by = UserSerializer(read_only=True)
    source_label = serializers.CharField(source='get_source_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    verification_entries = serializers.SerializerMethodField()
    verification_summary = serializers.SerializerMethodField()

    class Meta:
        model = StreakRedemptionRequest
        fields = [
            'id',
            'user',
            'source',
            'source_label',
            'amount',
            'hi_rollin_username',
            'status',
            'status_label',
            'note',
            'staff_note',
            'source_payload',
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
        if obj.source != StreakRedemptionRequest.SOURCE_LOGIN_STREAK:
            return []
        requested_date = obj.created_at.date()
        entries = (
            LoginStreakEntry.objects
            .filter(user=obj.user, login_date__lte=requested_date)
            .order_by('-login_date', '-created_at')[:STREAK_TARGET_DAYS]
        )
        return LoginStreakEntrySerializer(reversed(list(entries)), many=True).data

    def get_verification_summary(self, obj):
        if obj.source != StreakRedemptionRequest.SOURCE_LOGIN_STREAK:
            return {
                'target_days': STREAK_TARGET_DAYS,
                'record_count': 0,
                'is_consecutive': False,
                'start_date': None,
                'end_date': None,
            }
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
    last_scratch_redemption_request = serializers.SerializerMethodField()
    last_win_redemption_request = serializers.SerializerMethodField()

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
            'last_scratch_redemption_request',
            'last_win_redemption_request',
        ]
        read_only_fields = fields

    def get_target_days(self, obj):
        return STREAK_TARGET_DAYS

    def get_reward_amount(self, obj):
        return str(STREAK_REWARD_AMOUNT)

    def get_active_redemption_request(self, obj):
        request = (
            StreakRedemptionRequest.objects
            .filter(
                user=obj.user,
                source=StreakRedemptionRequest.SOURCE_LOGIN_STREAK,
                status__in=StreakRedemptionRequest.ACTIVE_STATUSES,
            )
            .order_by('-created_at')
            .first()
        )
        if not request:
            return None
        return StreakRedemptionRequestSerializer(request).data

    def get_last_win_redemption_request(self, obj):
        request = (
            StreakRedemptionRequest.objects
            .filter(user=obj.user, source=StreakRedemptionRequest.SOURCE_WIN_BONUS)
            .order_by('-created_at')
            .first()
        )
        if not request:
            return None
        return StreakRedemptionRequestSerializer(request).data

    def get_last_scratch_redemption_request(self, obj):
        request = (
            StreakRedemptionRequest.objects
            .filter(user=obj.user, source=StreakRedemptionRequest.SOURCE_SCRATCH_BONUS)
            .order_by('-created_at')
            .first()
        )
        if not request:
            return None
        return StreakRedemptionRequestSerializer(request).data

    def get_last_redemption_request(self, obj):
        request = (
            StreakRedemptionRequest.objects
            .filter(user=obj.user, source=StreakRedemptionRequest.SOURCE_LOGIN_STREAK)
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
