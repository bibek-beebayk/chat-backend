from collections import namedtuple

RankTier = namedtuple('RankTier', ['slug', 'label', 'min_xp'])

# Sorted ascending by min_xp; the first tier must be min_xp=0 so every user
# always resolves to a rank. Asserted below rather than silently trusted -
# a misordered/misconfigured list here is a boundary bug that would
# otherwise fail silently in rank_for_xp().
RANK_THRESHOLDS = [
    RankTier('bronze', 'Bronze', 0),
    RankTier('silver', 'Silver', 1000),
    RankTier('gold', 'Gold', 2500),
    RankTier('platinum', 'Platinum', 5000),
    RankTier('diamond', 'Diamond', 9000),
    RankTier('rollin_elite', 'Rollin Elite', 15000),
    RankTier('rollin_legend', 'Rollin Legend', 25000),
]

assert RANK_THRESHOLDS[0].min_xp == 0, 'first rank tier must start at 0 XP'
assert all(
    RANK_THRESHOLDS[i].min_xp < RANK_THRESHOLDS[i + 1].min_xp
    for i in range(len(RANK_THRESHOLDS) - 1)
), 'RANK_THRESHOLDS must be strictly ascending'

RANKS_BY_SLUG = {tier.slug: tier for tier in RANK_THRESHOLDS}


def rank_for_xp(total_xp):
    """Returns the RankTier whose min_xp is the highest one <= total_xp. Boundary is inclusive: total_xp == tier.min_xp reaches that tier."""
    current = RANK_THRESHOLDS[0]
    for tier in RANK_THRESHOLDS:
        if total_xp >= tier.min_xp:
            current = tier
        else:
            break
    return current


def next_rank_for_xp(total_xp):
    """The tier after the current one, or None if already at the top rank."""
    current = rank_for_xp(total_xp)
    index = RANK_THRESHOLDS.index(current)
    if index + 1 >= len(RANK_THRESHOLDS):
        return None
    return RANK_THRESHOLDS[index + 1]


def sub_ranges_for_tier(tier_slug):
    """
    The 3 even sub-level (I/II/III) XP ranges within one tier - static tier
    metadata, independent of any specific player. Returns None for a tier
    with no next tier (the uncapped top rank), which has no sub-levels by
    design - the Rollin Levels UI shows it as a distinct "prestige" state.
    """
    tier = RANKS_BY_SLUG[tier_slug]
    index = RANK_THRESHOLDS.index(tier)
    if index + 1 >= len(RANK_THRESHOLDS):
        return None
    next_tier = RANK_THRESHOLDS[index + 1]

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
    Returns None for the top (uncapped) tier (see sub_ranges_for_tier).
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
