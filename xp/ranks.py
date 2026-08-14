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
