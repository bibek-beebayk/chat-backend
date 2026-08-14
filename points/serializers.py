from rest_framework import serializers
from accounts.serializers import UserSerializer
from .models import PointAction, PointsBalance, PointsLedgerEntry, PointsRedemptionRequest


class PointActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PointAction
        fields = [
            'id',
            'slug',
            'label',
            'points_value',
            'is_active',
            'description',
            'max_awards_per_day',
        ]
        read_only_fields = fields


class PointsBalanceSerializer(serializers.ModelSerializer):
    # Scoped to the requesting user's own record (mirrors
    # rewards.serializers's active_redemption_request pattern for streak
    # requests) - players need this to see their own pending/approved
    # redemption without hitting the staff-only redemption_list_view.
    active_redemption_request = serializers.SerializerMethodField()

    class Meta:
        model = PointsBalance
        fields = [
            'balance',
            'lifetime_earned',
            'active_redemption_request',
            'updated_at',
        ]
        read_only_fields = fields

    def get_active_redemption_request(self, obj):
        request_obj = (
            PointsRedemptionRequest.objects
            .filter(user=obj.user, status__in=PointsRedemptionRequest.ACTIVE_STATUSES)
            .order_by('-created_at')
            .first()
        )
        if not request_obj:
            return None
        return PointsRedemptionRequestSerializer(request_obj).data


class PointsLedgerEntrySerializer(serializers.ModelSerializer):
    action = PointActionSerializer(read_only=True)

    class Meta:
        model = PointsLedgerEntry
        fields = [
            'id',
            'entry_type',
            'delta',
            'balance_after',
            'action',
            'note',
            'metadata',
            'created_at',
        ]
        read_only_fields = fields


class PointsRedemptionRequestSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    reviewed_by = UserSerializer(read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PointsRedemptionRequest
        fields = [
            'id',
            'user',
            'points_amount',
            'reward_description',
            'status',
            'status_label',
            'note',
            'staff_note',
            'conversion_rate_snapshot',
            'hi_rollin_credit_amount',
            'reviewed_by',
            'reviewed_at',
            'completed_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class RedemptionCreateSerializer(serializers.Serializer):
    points_amount = serializers.IntegerField(min_value=1)
    reward_description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class RedemptionStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[
        PointsRedemptionRequest.STATUS_APPROVED,
        PointsRedemptionRequest.STATUS_COMPLETED,
        PointsRedemptionRequest.STATUS_REJECTED,
    ])
    staff_note = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate(self, attrs):
        status_value = attrs.get('status')
        staff_note = (attrs.get('staff_note') or '').strip()
        if status_value == PointsRedemptionRequest.STATUS_REJECTED and not staff_note:
            raise serializers.ValidationError({'staff_note': 'Rejection reason is required.'})
        attrs['staff_note'] = staff_note
        return attrs


class AwardPointsSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    action_slug = serializers.SlugField(max_length=64)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=200)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)
