from collections import namedtuple

from django.core.cache import cache

# Lightweight, pickle-safe projection of a Tier row, used for all rank math.
# The full model (badge art, timestamps) is read directly where needed - see
# xp.views.rank_tiers_view.
RankTier = namedtuple('RankTier', ['slug', 'label', 'min_xp', 'rank_up_bonus_rp'])

_CACHE_KEY = 'xp:rank_tiers:v1'
_CACHE_TTL = 300


def _load_tiers():
    # Local import - xp.models imports this module for invalidate_tier_cache().
    from .models import Tier

    rows = (
        Tier.objects
        .filter(is_active=True)
        .order_by('min_xp')
        .values_list('slug', 'name', 'min_xp', 'rank_up_bonus_rp')
    )
    return [RankTier(slug, name, min_xp, bonus) for slug, name, min_xp, bonus in rows]


def get_rank_tiers():
    """
    All active tiers as RankTier tuples, ascending by min_xp. Cached briefly
    (per process) and invalidated on any Tier.save()/delete().
    """
    tiers = cache.get(_CACHE_KEY)
    if tiers is None:
        tiers = _load_tiers()
        cache.set(_CACHE_KEY, tiers, _CACHE_TTL)
    return tiers


def invalidate_tier_cache():
    cache.delete(_CACHE_KEY)


def rank_by_slug(slug):
    for tier in get_rank_tiers():
        if tier.slug == slug:
            return tier
    return None


def rank_for_xp(total_xp):
    """
    The tier whose min_xp is the highest one <= total_xp. Boundary is
    inclusive: total_xp == tier.min_xp reaches that tier.
    """
    tiers = get_rank_tiers()
    if not tiers:
        raise RuntimeError('No active Tier rows configured - seed the Rollin Levels ladder (xp.Tier).')
    current = tiers[0]
    for tier in tiers:
        if total_xp >= tier.min_xp:
            current = tier
        else:
            break
    return current


def next_rank_for_xp(total_xp):
    """The tier after the current one, or None if already at the top tier."""
    tiers = get_rank_tiers()
    current = rank_for_xp(total_xp)
    index = tiers.index(current)
    if index + 1 >= len(tiers):
        return None
    return tiers[index + 1]


def sub_ranges_for_tier(tier_slug):
    """
    The 3 even sub-level (I/II/III) XP ranges within one tier - static tier
    metadata, independent of any specific player. Returns None for the top
    (uncapped) tier, which has no sub-levels by design.
    """
    tiers = get_rank_tiers()
    tier = rank_by_slug(tier_slug)
    if tier is None:
        return None
    index = tiers.index(tier)
    if index + 1 >= len(tiers):
        return None
    next_tier = tiers[index + 1]

    span = next_tier.min_xp - tier.min_xp
    step = span // 3
    # Fold the integer-division remainder into sub-level III so the three
    # ranges always sum to the full span with no gap.
    boundaries = [
        tier.min_xp,
        tier.min_xp + step,
        tier.min_xp + step * 2,
        next_tier.min_xp,
    ]
    return [
        {'sub_level': i + 1, 'sub_level_label': label, 'min_xp': boundaries[i], 'max_xp': boundaries[i + 1] - 1}
        for i, label in enumerate(('I', 'II', 'III'))
    ]


def sub_level_for_xp(total_xp):
    """
    Which of the player's current tier's 3 sub-levels total_xp falls into,
    plus progress within it - computed live, no stored sub-tier concept.
    Returns None for the top (uncapped) tier.
    """
    tier = rank_for_xp(total_xp)
    ranges = sub_ranges_for_tier(tier.slug)
    if ranges is None:
        return None

    current = ranges[-1]
    for sub_range in ranges:
        if total_xp <= sub_range['max_xp']:
            current = sub_range
            break

    sub_span = (current['max_xp'] - current['min_xp']) + 1
    progress = int(min(100, max(0, (total_xp - current['min_xp']) / sub_span * 100)))

    return {
        'sub_level': current['sub_level'],
        'sub_level_label': current['sub_level_label'],
        'sub_level_min_xp': current['min_xp'],
        'sub_level_max_xp': current['max_xp'],
        'sub_level_progress_percent': progress,
    }
