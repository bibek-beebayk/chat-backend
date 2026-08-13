# Only 8 rows is offered for now (12/16 disabled at the product level, not
# removed - MULTIPLIER_TABLES below still has both, so this is a one-line
# revert if they're re-enabled later).
ROWS_CHOICES = (8,)
RISK_CHOICES = ('low', 'medium', 'high')

GAME_SLUG = 'plinko'

# Players can only wager one of these fixed amounts (not an arbitrary range).
WAGER_OPTIONS = (5, 10)

# Drop-position bias: only the first BIAS_ROWS bounces have their probability
# shifted toward the side the player dropped from; the rest stay a fair coin.
# Bounding the number of biased flips (rather than biasing all `rows` flips)
# keeps the worst-case EV across every multiplier table safely under 1.0 even
# at maximum drag - see plinko/tests.py::test_bias_worst_case_ev_stays_safe
# for the verification. Biasing every row instead would let a player push
# several tables well past 100% RTP with only a few points of shift.
# NOTE: play_round() no longer feeds a client-supplied drop_offset into
# generate_path() at all (see services.py) - the drag-to-bias mechanic these
# constants were built for was replaced by a fixed center drop, so this is
# now a dormant capability rather than a live one. It's kept (and still
# tested) as a documented safety property, not because it's reachable today.
BIAS_ROWS = 2
MAX_BIAS = 0.18

# Each table has `rows + 1` symmetric slots, indexed by slot_index = count of
# "right" bounces (a Binomial(rows, 0.5) distribution: edges rare/high-payout,
# center common/low-payout). Verified via exact binomial EV calculation.
# rows=8 is the only row count currently offered (see ROWS_CHOICES above) and
# was retuned to a ~92-98.5% RTP band (1.5%-8.1% house edge) at the product
# owner's request for slightly more generous payouts; rows=12/16 are dormant
# and were left at their original ~89-97% RTP tuning. See plinko/tests.py::
# test_multiplier_table_expected_values for the regression guard.
MULTIPLIER_TABLES = {
    8: {
        'low':    [5.57, 2.09, 1.1, 0.99, 0.5, 0.99, 1.1, 2.09, 5.57],
        'medium': [12.75, 2.93, 1.28, 0.69, 0.39, 0.69, 1.28, 2.93, 12.75],
        'high':   [26.97, 3.72, 1.39, 0.28, 0.18, 0.28, 1.39, 3.72, 26.97],
    },
    12: {
        'low':    [9.35, 4.68, 1.87, 1.31, 1.03, 0.94, 0.56, 0.94, 1.03, 1.31, 1.87, 4.68, 9.35],
        'medium': [21.8, 7.27, 2.73, 1.73, 1.18, 0.64, 0.36, 0.64, 1.18, 1.73, 2.73, 7.27, 21.8],
        'high':   [50.7, 13.1, 5.25, 1.75, 0.96, 0.44, 0.17, 0.44, 0.96, 1.75, 5.25, 13.1, 50.7],
    },
    16: {
        'low':    [18.6, 10.4, 2.32, 1.62, 1.39, 1.28, 1.16, 0.81, 0.58, 0.81, 1.16, 1.28, 1.39, 1.62, 2.32, 10.4, 18.6],
        'medium': [52.0, 17.7, 7.09, 3.55, 2.36, 1.54, 0.95, 0.59, 0.35, 0.59, 0.95, 1.54, 2.36, 3.55, 7.09, 17.7, 52.0],
        'high':   [178, 41.0, 16.4, 6.83, 2.73, 1.37, 0.68, 0.41, 0.27, 0.41, 0.68, 1.37, 2.73, 6.83, 16.4, 41.0, 178],
    },
}


def get_multiplier_table(rows, risk_level):
    return MULTIPLIER_TABLES[rows][risk_level]
