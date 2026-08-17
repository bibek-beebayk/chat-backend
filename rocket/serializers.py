from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from .constants import MAX_AUTO_CASHOUT_MULTIPLIER, MAX_WAGER, MIN_AUTO_CASHOUT_MULTIPLIER, MIN_WAGER
from .models import RocketRound
from .services import multiplier_at_elapsed


class RocketPlayRequestSerializer(serializers.Serializer):
    wager_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=MIN_WAGER, max_value=MAX_WAGER)
    auto_cashout_multiplier = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, allow_null=True,
        min_value=MIN_AUTO_CASHOUT_MULTIPLIER, max_value=MAX_AUTO_CASHOUT_MULTIPLIER,
    )
    client_request_id = serializers.CharField(required=False, allow_blank=True, max_length=64)


class RocketRoundSerializer(serializers.ModelSerializer):
    """
    Serializes a round's *current* state - never includes crash_point while
    status=active (only the live-computed `multiplier` for that phase); once
    resolved, `multiplier` reflects the final outcome (cashout_multiplier or
    the now-revealed crash_point). This is the one place the frontend's
    "visual multiplier" is allowed to come from - see rocket/services.py's
    module docstring for why re-deriving it fresh here (rather than trusting
    a client-sent value) is what keeps display, cashout, and crash always
    consistent.
    """
    round_id = serializers.IntegerField(source='id', read_only=True)
    phase = serializers.SerializerMethodField()
    multiplier = serializers.SerializerMethodField()
    seconds_remaining = serializers.SerializerMethodField()

    class Meta:
        model = RocketRound
        fields = [
            'round_id', 'status', 'phase', 'wager_amount', 'auto_cashout_multiplier',
            'multiplier', 'seconds_remaining', 'started_at',
            'cashout_multiplier', 'payout_amount', 'balance_after',
            'created_at', 'resolved_at',
        ]
        read_only_fields = fields

    def _elapsed(self, obj):
        return Decimal(str((timezone.now() - obj.started_at).total_seconds()))

    def get_phase(self, obj):
        if obj.status == RocketRound.STATUS_CASHED_OUT:
            return 'cashed_out'
        if obj.status == RocketRound.STATUS_CRASHED:
            return 'crashed'
        return 'countdown' if self._elapsed(obj) <= 0 else 'running'

    def get_multiplier(self, obj):
        if obj.status == RocketRound.STATUS_CASHED_OUT:
            return str(obj.cashout_multiplier)
        if obj.status == RocketRound.STATUS_CRASHED:
            return str(obj.crash_point)
        return str(multiplier_at_elapsed(self._elapsed(obj)))

    def get_seconds_remaining(self, obj):
        if obj.status != RocketRound.STATUS_ACTIVE:
            return None
        elapsed = self._elapsed(obj)
        return str(-elapsed) if elapsed < 0 else None


class RocketHistoryItemSerializer(serializers.ModelSerializer):
    round_id = serializers.IntegerField(source='id', read_only=True)
    result_multiplier = serializers.SerializerMethodField()

    class Meta:
        model = RocketRound
        fields = ['round_id', 'status', 'wager_amount', 'result_multiplier', 'payout_amount', 'created_at']
        read_only_fields = fields

    def get_result_multiplier(self, obj):
        if obj.status == RocketRound.STATUS_CASHED_OUT:
            return str(obj.cashout_multiplier)
        if obj.status == RocketRound.STATUS_CRASHED:
            return str(obj.crash_point)
        return None
