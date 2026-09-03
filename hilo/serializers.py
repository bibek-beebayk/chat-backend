from rest_framework import serializers

from .constants import MAX_WAGER, MIN_WAGER
from .models import HiLoRound, HiLoStep
from .services import payout_for, quote


class HiLoPlayRequestSerializer(serializers.Serializer):
    wager_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=MIN_WAGER, max_value=MAX_WAGER)
    client_request_id = serializers.CharField(required=False, allow_blank=True, max_length=64)


class HiLoPredictRequestSerializer(serializers.Serializer):
    prediction = serializers.ChoiceField(choices=[HiLoStep.PREDICTION_HIGHER, HiLoStep.PREDICTION_LOWER])
    # The step the client believes it is resolving. Required (not defaulted)
    # so a client that forgets it fails loudly rather than silently losing
    # the duplicate-prediction protection it exists for - see
    # services.predict.
    step_index = serializers.IntegerField(min_value=0)


class HiLoRoundSerializer(serializers.ModelSerializer):
    """
    A round's current state. There is no hidden outcome to withhold here -
    the next card is not generated until a predict request arrives - so
    everything the client needs to render is exposed, including the live
    quote for both directions. That quote is display-only: services.predict
    recomputes it server-side on every prediction and never accepts a
    client-sent value.
    """

    round_id = serializers.IntegerField(source='id', read_only=True)
    current_card = serializers.SerializerMethodField()
    odds = serializers.SerializerMethodField()
    potential_payout = serializers.SerializerMethodField()
    can_cash_out = serializers.SerializerMethodField()

    class Meta:
        model = HiLoRound
        fields = [
            'round_id', 'status', 'wager_amount', 'current_card', 'multiplier',
            'streak', 'steps_taken', 'odds', 'potential_payout', 'can_cash_out',
            'capped', 'payout_amount', 'balance_after', 'created_at', 'resolved_at',
        ]
        read_only_fields = fields

    def get_current_card(self, obj):
        return {'rank': obj.current_rank, 'suit': obj.current_suit}

    def get_odds(self, obj):
        # Only meaningful while a prediction can still be made.
        if obj.status != HiLoRound.STATUS_ACTIVE:
            return None
        return quote(obj.current_rank)

    def get_potential_payout(self, obj):
        if obj.status != HiLoRound.STATUS_ACTIVE:
            return str(obj.payout_amount)
        return str(payout_for(obj.wager_amount, obj.multiplier))

    def get_can_cash_out(self, obj):
        return obj.status == HiLoRound.STATUS_ACTIVE and obj.multiplier > 1


class HiLoStepSerializer(serializers.ModelSerializer):
    from_card = serializers.SerializerMethodField()
    to_card = serializers.SerializerMethodField()

    class Meta:
        model = HiLoStep
        fields = [
            'step_index', 'from_card', 'prediction', 'to_card', 'outcome',
            'step_multiplier', 'multiplier_after', 'created_at',
        ]
        read_only_fields = fields

    def get_from_card(self, obj):
        return {'rank': obj.from_rank, 'suit': obj.from_suit}

    def get_to_card(self, obj):
        return {'rank': obj.to_rank, 'suit': obj.to_suit}


class HiLoHistoryItemSerializer(serializers.ModelSerializer):
    round_id = serializers.IntegerField(source='id', read_only=True)
    steps = HiLoStepSerializer(many=True, read_only=True)

    class Meta:
        model = HiLoRound
        fields = [
            'round_id', 'status', 'wager_amount', 'multiplier', 'streak',
            'payout_amount', 'capped', 'created_at', 'steps',
        ]
        read_only_fields = fields
