from rest_framework import serializers
from .models import XPAction, XPBalance
from .ranks import next_rank_for_xp, rank_for_xp


class XPActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = XPAction
        fields = [
            'id',
            'slug',
            'label',
            'xp_value',
            'is_active',
            'description',
            'max_awards_per_day',
            'challenge_target_count',
            'challenge_source_action',
        ]


class XPStatusSerializer(serializers.ModelSerializer):
    rank = serializers.SerializerMethodField()
    rank_label = serializers.SerializerMethodField()
    rank_min_xp = serializers.SerializerMethodField()
    next_rank = serializers.SerializerMethodField()
    next_rank_xp = serializers.SerializerMethodField()
    xp_to_next_rank = serializers.SerializerMethodField()
    rank_progress_percent = serializers.SerializerMethodField()
    global_rank = serializers.SerializerMethodField()

    class Meta:
        model = XPBalance
        fields = [
            'total_xp',
            'rank',
            'rank_label',
            'rank_min_xp',
            'next_rank',
            'next_rank_xp',
            'xp_to_next_rank',
            'rank_progress_percent',
            'global_rank',
            'updated_at',
        ]

    def get_rank(self, obj):
        return rank_for_xp(obj.total_xp).slug

    def get_rank_label(self, obj):
        return rank_for_xp(obj.total_xp).label

    def get_rank_min_xp(self, obj):
        return rank_for_xp(obj.total_xp).min_xp

    def get_next_rank(self, obj):
        next_tier = next_rank_for_xp(obj.total_xp)
        return next_tier.slug if next_tier else None

    def get_next_rank_xp(self, obj):
        next_tier = next_rank_for_xp(obj.total_xp)
        return next_tier.min_xp if next_tier else None

    def get_xp_to_next_rank(self, obj):
        next_tier = next_rank_for_xp(obj.total_xp)
        return (next_tier.min_xp - obj.total_xp) if next_tier else 0

    def get_rank_progress_percent(self, obj):
        current = rank_for_xp(obj.total_xp)
        next_tier = next_rank_for_xp(obj.total_xp)
        if next_tier is None:
            return 100
        span = next_tier.min_xp - current.min_xp
        if span <= 0:
            return 100
        progressed = obj.total_xp - current.min_xp
        return max(0, min(100, round(progressed * 100 / span)))

    def get_global_rank(self, obj):
        # 1-indexed position among all players by total XP - not cached
        # anywhere (XPBalance.rank_slug is a tier cache, not a position), so
        # this is a live COUNT each time status is fetched. Cheap: one
        # indexed count query, no new model needed.
        return XPBalance.objects.filter(total_xp__gt=obj.total_xp).count() + 1
