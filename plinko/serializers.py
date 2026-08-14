import math

from rest_framework import serializers
from .constants import RISK_CHOICES, ROWS_CHOICES, WAGER_OPTIONS
from .free_drop_constants import FREE_DROP_ROWS_CHOICES
from .models import PlinkoRound

# Tolerance for floating-point drift from the client's own [-1, 1]
# normalization math (e.g. -1.0000000000000002) - a drop the player placed
# legitimately at the extreme edge must not be rejected over this. Values
# materially outside the legal range (1.2, -1.4, ...) are still rejected.
DROP_POSITION_EPSILON = 1e-6


class PlinkoPlayRequestSerializer(serializers.Serializer):
    rows = serializers.ChoiceField(choices=ROWS_CHOICES)
    risk_level = serializers.ChoiceField(choices=RISK_CHOICES)
    wager_amount = serializers.ChoiceField(choices=WAGER_OPTIONS)
    drop_offset = serializers.FloatField(required=False, default=0.0, min_value=-1.0, max_value=1.0)


class FreeDropPlayRequestSerializer(serializers.Serializer):
    rows = serializers.ChoiceField(choices=FREE_DROP_ROWS_CHOICES)
    risk_level = serializers.ChoiceField(choices=RISK_CHOICES)
    wager_amount = serializers.ChoiceField(choices=WAGER_OPTIONS)
    # No min_value/max_value here - DRF's built-in range validators reject
    # a hair outside [-1, 1] with no tolerance for float noise, and don't
    # guard against non-finite values (NaN/Infinity silently pass their
    # </>-based comparisons). validate_drop_position below handles both.
    drop_position = serializers.FloatField()

    def validate_drop_position(self, value):
        if not math.isfinite(value):
            raise serializers.ValidationError('drop_position must be a finite number.')
        if value < -1.0 - DROP_POSITION_EPSILON or value > 1.0 + DROP_POSITION_EPSILON:
            raise serializers.ValidationError('drop_position must be between -1.0 and 1.0.')
        return max(-1.0, min(1.0, value))


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
            'physics_seed',
            'balance_after',
            'created_at',
        ]
        read_only_fields = fields
