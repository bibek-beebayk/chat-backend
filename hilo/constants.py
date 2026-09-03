from decimal import Decimal

# Game identity/version - every HiLoRound records the GAME_VERSION active at
# start time, mirroring slots/rocket, so a future odds/edge change bumps this
# rather than silently reinterpreting historical rounds.
GAME_SLUG = 'hilo'
GAME_VERSION = 'hilo_v1'

# --- Cards ---
# Ace high (2 < 3 < ... < K < A). RANKS is ordered, and a rank's numeric
# value is its index + 2, so RANK_VALUES is derived rather than duplicated.
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
RANK_VALUES = {rank: index + 2 for index, rank in enumerate(RANKS)}
SUITS = ['hearts', 'diamonds', 'clubs', 'spades']
RANK_COUNT = len(RANKS)

# Cards are generated independently (not dealt from a depleting deck) - see
# services.draw_card. This keeps every quote on screen exactly equal to the
# probability actually used, with no deck state to persist, leak, or count.

# --- Wagering ---
# Free-form amount input with quick-select shortcuts, same shape as Rocket
# (Plinko/Slots use fixed choice sets instead).
MIN_WAGER = Decimal('1')
MAX_WAGER = Decimal('1000')
WAGER_QUICK_AMOUNTS = [5, 10, 20, 50]

# --- Payout math (house edge / RTP knobs) ---
# See services.step_multiplier for the derivation. With the equal-card =
# push rule, a push returns the round to an equivalent state (same
# multiplier, new card, fresh quote), so a prediction is settled entirely
# by the non-push branch - which is what the step multiplier conditions on.
HOUSE_EDGE = Decimal('0.03')

# On a 2 the HIGHER branch (and on an ace the LOWER branch) is a certainty
# once pushes are excluded, so the raw step would be (1 - HOUSE_EDGE) = 0.97
# and a *correct* prediction would shrink the accumulated multiplier. This
# floor costs a sliver of edge on two ranks out of thirteen and buys the one
# invariant players actually check: a correct call never lowers your
# multiplier. See services.step_multiplier.
MIN_STEP_MULTIPLIER = Decimal('1.01')

# Jackpot-style ceiling (design spec s16): on reaching this the server
# force-cashes-out the round rather than leaving a live round the player
# can no longer meaningfully act on.
MAX_MULTIPLIER = Decimal('100.00')
# Independent of the multiplier cap - MAX_MULTIPLIER * MAX_WAGER would be
# 100,000 points, which the economy shouldn't expose on a single round.
MAX_PAYOUT = Decimal('50000.00')
# Hard stop on round length. Unreachable in practice (the multiplier cap
# bites long before it on any sane line of play), but it bounds the number
# of HiLoStep rows a single round can ever produce.
MAX_STEPS = 25

# --- XP / achievement thresholds ---
# Kept here rather than hardcoded in xp_hooks.py so they can be tuned
# without touching game logic. Slugs are seeded in migration 0003.
CASHOUT_ACHIEVEMENT_THRESHOLDS = [Decimal('2'), Decimal('5'), Decimal('10')]
STREAK_ACHIEVEMENT_LENGTHS = [5, 10]

HISTORY_LIMIT = 20
