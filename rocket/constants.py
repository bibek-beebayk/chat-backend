from decimal import Decimal

# Game identity/version - every RocketRound records the GAME_VERSION active
# at play time, mirroring slots/constants.py's convention, so a future
# curve/distribution change bumps this rather than silently reinterpreting
# historical rounds.
GAME_SLUG = 'rocket'
GAME_VERSION = 'rocket_v1'

# Play amount is a free-form input with quick-select shortcuts (not a fixed
# choice set like Plinko/Slots), per the product spec's "play amount input"
# + "configurable quick amount buttons" requirement.
MIN_WAGER = Decimal('1')
MAX_WAGER = Decimal('1000')
WAGER_QUICK_AMOUNTS = [10, 50, 100, 500]

# Seconds between a round being created (play accepted) and the multiplier
# actually starting to climb - purely a presentation delay (lets the
# frontend show a "3... 2... 1..." countdown) with zero effect on the math:
# services.multiplier_at_elapsed() treats any elapsed time <= 0 as still in
# the countdown phase, so no separate DB status is needed for it.
COUNTDOWN_SECONDS = Decimal('3')

# --- Crash-point distribution (house edge / RTP knobs) ---
# Standard "provably fair" crash formula: crash = (1 - HOUSE_EDGE) / (1 - r)
# for a uniform random r in [0, 1). This construction has the property that
# cashing out at any FIXED multiplier M has expected return exactly
# (1 - HOUSE_EDGE) per unit staked - P(crash >= M) = (1-HOUSE_EDGE)/M, so
# E[return] = P(crash >= M) * M = (1-HOUSE_EDGE) for every M >= 1, i.e. RTP
# is uniform across every cashout strategy, not just on average. See
# rocket/tests.py::RocketMathTests for an empirical check of this property.
HOUSE_EDGE = Decimal('0.04')  # -> ~96% RTP from the smooth-tail formula alone
# A flat extra chance of an immediate 1.00x crash, on top of whatever the
# formula above would naturally produce near r=0 - matches real crash
# games' visible "instant bust" rounds and gives ops one more directly
# tunable "how often does the rocket not even take off" knob, independent
# of the smooth-tail formula. This forces that fraction of rounds to crash
# at 1.00x regardless of the formula's outcome, which scales the *actual*
# achievable RTP for any cashout > 1x down to roughly
# (1 - INSTANT_CRASH_PROBABILITY) * (1 - HOUSE_EDGE) - with the defaults
# below, ~0.97 * 0.96 = ~93.1% - see
# rocket/tests.py::test_rtp_is_approximately_uniform_across_fixed_cashout_strategies.
INSTANT_CRASH_PROBABILITY = Decimal('0.03')
# Sanity ceiling - without this, an extreme r arbitrarily close to 1 could
# produce an astronomically large (and astronomically long-running, per the
# multiplier curve below) crash point.
MAX_CRASH_MULTIPLIER = Decimal('1000.00')

# --- Multiplier growth curve ---
# multiplier(t) = e^(GROWTH_RATE * t^ACCEL_EXPONENT) for elapsed seconds t.
# ACCEL_EXPONENT > 1 makes the *rate* of growth itself increase over time
# (not just compound growth at a fixed rate), matching the "increase
# smoothly and accelerate over time rather than increasing linearly"
# requirement - with these constants the curve reaches ~2x around 5s,
# ~7-8x around 8s, ~25x around 12s, ~65x around 15s, so most rounds (which
# crash at low multipliers per the distribution above) resolve within a
# few seconds, and rare high-multiplier survivors take correspondingly
# (and excitingly) longer, capped around ~23s at MAX_CRASH_MULTIPLIER.
GROWTH_RATE = Decimal('0.15')
ACCEL_EXPONENT = Decimal('1.25')

MIN_AUTO_CASHOUT_MULTIPLIER = Decimal('1.01')
MAX_AUTO_CASHOUT_MULTIPLIER = MAX_CRASH_MULTIPLIER
AUTO_CASHOUT_QUICK_OPTIONS = [Decimal('1.5'), Decimal('2.0'), Decimal('3.0'), Decimal('5.0')]

# Cashout-multiplier achievement thresholds (XP awarded once per round that
# clears each). Kept here rather than hardcoded in services.py so they can
# be tuned without touching game logic. The 10x tier is "Moon Walker".
CASHOUT_ACHIEVEMENT_THRESHOLDS = [Decimal('2'), Decimal('5'), Decimal('10')]
# "Five Alive" - this many consecutive successful cash-outs in a row.
FIVE_ALIVE_STREAK_LENGTH = 5

HISTORY_LIMIT = 20
