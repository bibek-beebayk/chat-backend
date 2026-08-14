from rest_framework import serializers
from .constants import RISK_CHOICES, ROWS_CHOICES, WAGER_OPTIONS
from .free_drop_constants import FREE_DROP_ROWS_CHOICES
from .models import PlinkoRound


class PlinkoPlayRequestSerializer(serializers.Serializer):
    rows = serializers.ChoiceField(choices=ROWS_CHOICES)
    risk_level = serializers.ChoiceField(choices=RISK_CHOICES)
    wager_amount = serializers.ChoiceField(choices=WAGER_OPTIONS)
    drop_offset = serializers.FloatField(required=False, default=0.0, min_value=-1.0, max_value=1.0)


class FreeDropPlayRequestSerializer(serializers.Serializer):
    rows = serializers.ChoiceField(choices=FREE_DROP_ROWS_CHOICES)
    risk_level = serializers.ChoiceField(choices=RISK_CHOICES)
    wager_amount = serializers.ChoiceField(choices=WAGER_OPTIONS)
    drop_position = serializers.FloatField(min_value=-1.0, max_value=1.0)


class PlinkoRoundSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlinkoRound
        fields = [
            'id',
            'mode',
            'rows',
            'risk_level',
            'wager_amount',
            'slot_index',
            'multiplier',
            'payout_amount',
            'path',
            'drop_offset',
            'drop_position',
            'balance_after',
            'created_at',
        ]
        read_only_fields = fields
