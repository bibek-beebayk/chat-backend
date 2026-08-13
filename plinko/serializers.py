from rest_framework import serializers
from .constants import MAX_WAGER, MIN_WAGER, RISK_CHOICES, ROWS_CHOICES
from .models import PlinkoRound


class PlinkoPlayRequestSerializer(serializers.Serializer):
    rows = serializers.ChoiceField(choices=ROWS_CHOICES)
    risk_level = serializers.ChoiceField(choices=RISK_CHOICES)
    wager_amount = serializers.IntegerField(min_value=MIN_WAGER, max_value=MAX_WAGER)
    drop_offset = serializers.FloatField(required=False, default=0.0, min_value=-1.0, max_value=1.0)


class PlinkoRoundSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlinkoRound
        fields = [
            'id',
            'rows',
            'risk_level',
            'wager_amount',
            'slot_index',
            'multiplier',
            'payout_amount',
            'path',
            'drop_offset',
            'balance_after',
            'created_at',
        ]
        read_only_fields = fields
