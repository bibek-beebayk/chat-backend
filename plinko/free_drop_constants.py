# Free Drop is a separate Plinko mode from Classic (see plinko/constants.py) -
# nothing here is read by, or affects, Classic's game logic or tables.

# Only 8 rows for the first implementation, matching Classic's current
# restriction. PEGS_PER_ROW is keyed by rows (not hardcoded) so 12/16 can be
# added later without a rewrite.
FREE_DROP_ROWS_CHOICES = (8,)

# Equal-pegs-per-row board (not triangular). pegsPerRow = rows, not an
# independently chosen number: the ball's landing slot comes from a random
# walk of exactly `rows` left/right bounces (one per row passed), which has
# rows+1 possible outcomes regardless of how many pegs sit in a row - so the
# *last* row's peg count is what has to match rows+1 slots, exactly like
# Classic's triangular board (whose last row also has `rows` pegs for the
# same reason). Choosing pegsPerRow bigger than rows would create extra
# visual slots the outcome model can never actually land on (dead bins);
# choosing it smaller would run out of columns for the ball to weave
# through. pegsPerRow = rows is what "produces the cleanest board geometry
# and correct number of landing slots" per the design brief.
PEGS_PER_ROW = {
    8: 8,
}

GAME_SLUG = 'plinko'

# Drop-position bias: the same bounded-bias-rows mechanism already proven
# safe for Classic (see plinko/constants.py's BIAS_ROWS/MAX_BIAS comment),
# but here it's the live, primary mechanic - a player's chosen drop_position
# directly sets biased_p = 0.5 + drop_position * FREE_DROP_MAX_BIAS for the
# first FREE_DROP_BIAS_ROWS bounces, the rest stay a fair coin. These exact
# values (and the table below) were verified via plinko/tests.py::
# FreeDropMultiplierTableTests to keep worst-case EV (at drop_position
# +/-1.0, the extreme ends) safely under 99% for every risk tier - see that
# test for the regression guard.
FREE_DROP_BIAS_ROWS = 2
FREE_DROP_MAX_BIAS = 0.18

# Continuous drop_position is bucketed into this many buckets *only* for
# offline seed-table generation (picking a real, verified physics seed to
# replay) - never for the economic outcome, which always uses the exact
# continuous value the player chose. Odd so there's a true center bucket.
DROP_BUCKETS = 15

# Same shape as Classic's original (pre-RTP-bump) tables, which were already
# verified safe under a *live* bias mechanic - see the EV check in
# plinko/tests.py::FreeDropMultiplierTableTests. Deliberately not reusing
# Classic's current (higher) tables: those were only re-verified safe with
# the bias mechanic inert, and would exceed a safe RTP if biased live.
FREE_DROP_MULTIPLIER_TABLES = {
    8: {
        'low':    [5.49, 2.06, 1.08, 0.98, 0.49, 0.98, 1.08, 2.06, 5.49],
        'medium': [12.4, 2.85, 1.24, 0.67, 0.38, 0.67, 1.24, 2.85, 12.4],
        'high':   [26.3, 3.63, 1.36, 0.27, 0.18, 0.27, 1.36, 3.63, 26.3],
    },
}


def get_free_drop_multiplier_table(rows, risk_level):
    return FREE_DROP_MULTIPLIER_TABLES[rows][risk_level]


def get_pegs_per_row(rows):
    return PEGS_PER_ROW[rows]
