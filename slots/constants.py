from decimal import Decimal

# Game identity/version. Every SlotRound records the GAME_VERSION active at
# spin time - changing reel strips/paytable/paylines later must bump this
# constant (e.g. 'slot_v2') rather than mutate slot_v1's meaning, so historical
# rounds stay interpretable under the math that actually produced them.
GAME_SLUG = 'slots'
GAME_VERSION = 'slot_v1'

# Symbol IDs are the stable wire/storage identifiers - display labels are
# separate so re-theming never touches game logic or historical round data.
SYMBOLS = ['coin', 'gem', 'cards', 'bell', 'crown', 'seven']

SYMBOL_LABELS = {
    'coin': 'Rollin Coin',
    'gem': 'Purple Gem',
    'cards': 'Playing Cards',
    'bell': 'Bell',
    'crown': 'Crown',
    'seven': 'Golden 7',
}

# Multiplier paid when a payline shows 3-of-a-kind of this symbol. Applied to
# the *total* spin wager (not per-line). Tuned against simulate_slot_rtp
# (see slots/management/commands) to land ~95-97% RTP - see the module
# docstring on slots/services.py for the exact RTP formula these were
# derived from. Confirmed via a 10,000,000-spin simulation run: 95.71% RTP,
# 26.11% hit rate, 5.40% multi-line win rate, max observed payout 81x.
PAYTABLE = {
    'coin': Decimal('2'),
    'gem': Decimal('3'),
    'cards': Decimal('5'),
    'bell': Decimal('10'),
    'crown': Decimal('30'),
    'seven': Decimal('75'),
}

# 5 fixed paylines. Each entry is [row_for_reel0, row_for_reel1, row_for_reel2]
# where row 0 = top, 1 = middle, 2 = bottom. A line wins when all 3 selected
# cells hold the same symbol.
#
#   Line 0 - Middle:      Line 1 - Top:        Line 2 - Bottom:
#     - - -                 X X X                 - - -
#     X X X                 - - -                 - - -
#     - - -                 - - -                 X X X
#
#   Line 3 - V:           Line 4 - Inverted V:
#     X - X                  - - -
#     - X -                  - X -
#     - - -                  X - X
PAYLINES = [
    [1, 1, 1],
    [0, 0, 0],
    [2, 2, 2],
    [0, 1, 0],
    [2, 1, 2],
]

MIN_WAGER = 1
MAX_WAGER = 20
WAGER_PRESETS = [1, 5, 10, 20]

# Virtual reel strips - the sole source of truth for symbol frequency, hit
# rate, volatility, and RTP. Each reel is independently configurable; these
# three were generated once from a fixed per-symbol count distribution
# (coin=14, gem=10, cards=6, bell=5, crown=3, seven=2 out of 40) shuffled
# with a fixed seed per reel (see the generation script referenced in the
# services module docstring) so the order is reproducible/auditable, not
# regenerated at runtime. Changing the *frequency counts* changes RTP;
# changing only the *order* does not (the server samples a uniformly random
# stop per reel, so only relative symbol frequency affects the math).
REEL_1 = ['coin', 'coin', 'gem', 'gem', 'bell', 'gem', 'coin', 'gem', 'bell', 'cards', 'cards', 'seven', 'gem', 'seven', 'coin', 'gem', 'coin', 'gem', 'cards', 'coin', 'cards', 'coin', 'coin', 'bell', 'coin', 'coin', 'cards', 'crown', 'gem', 'coin', 'crown', 'gem', 'coin', 'bell', 'coin', 'cards', 'gem', 'bell', 'coin', 'crown']

REEL_2 = ['coin', 'coin', 'bell', 'coin', 'gem', 'cards', 'coin', 'bell', 'coin', 'coin', 'gem', 'coin', 'seven', 'gem', 'coin', 'gem', 'crown', 'crown', 'bell', 'seven', 'gem', 'gem', 'gem', 'gem', 'coin', 'coin', 'coin', 'gem', 'coin', 'gem', 'bell', 'cards', 'cards', 'coin', 'cards', 'crown', 'coin', 'cards', 'bell', 'cards']

REEL_3 = ['crown', 'coin', 'cards', 'cards', 'coin', 'cards', 'gem', 'gem', 'coin', 'gem', 'coin', 'bell', 'cards', 'coin', 'gem', 'coin', 'bell', 'coin', 'crown', 'coin', 'gem', 'coin', 'gem', 'gem', 'crown', 'coin', 'seven', 'bell', 'gem', 'bell', 'seven', 'cards', 'coin', 'cards', 'bell', 'gem', 'coin', 'coin', 'gem', 'coin']

REEL_STRIPS = [REEL_1, REEL_2, REEL_3]

assert all(set(strip) <= set(SYMBOLS) for strip in REEL_STRIPS), 'Reel strip contains an unknown symbol id.'
assert set(PAYTABLE.keys()) == set(SYMBOLS), 'Paytable must define every symbol exactly once.'
