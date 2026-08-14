from rest_framework import serializers
from .constants import WAGER_PRESETS
from .models import SlotRound


class SlotPlayRequestSerializer(serializers.Serializer):
    wager = serializers.ChoiceField(choices=WAGER_PRESETS)
    client_request_id = serializers.CharField(required=False, allow_blank=True, max_length=64)


class SlotRoundSerializer(serializers.ModelSerializer):
    round_id = serializers.IntegerField(source='id', read_only=True)
    wager = serializers.IntegerField(source='wager_amount', read_only=True)
    reel_stops = serializers.SerializerMethodField()
    grid = serializers.SerializerMethodField()
    payout = serializers.DecimalField(source='payout_amount', max_digits=12, decimal_places=2, read_only=True)
    net = serializers.DecimalField(source='net_result', max_digits=12, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(source='balance_after', max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = SlotRound
        fields = [
            'round_id',
            'game_version',
            'wager',
            'reel_stops',
            'grid',
            'winning_lines',
            'total_multiplier',
            'payout',
            'net',
            'balance',
            'created_at',
        ]
        read_only_fields = fields

    def get_reel_stops(self, obj):
        return [obj.reel_1_stop, obj.reel_2_stop, obj.reel_3_stop]

    def get_grid(self, obj):
        return obj.grid_snapshot
