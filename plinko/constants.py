# Only 8 rows is offered for now (12/16 disabled at the product level, not
# removed - MULTIPLIER_TABLES below still has both, so this is a one-line
# revert if they're re-enabled later).
ROWS_CHOICES = (8,)
RISK_CHOICES = ('low', 'medium', 'high')

GAME_SLUG = 'plinko'

MIN_WAGER = 1
MAX_WAGER = 100000

# Drop-position bias: only the first BIAS_ROWS bounces have their probability
# shifted toward the side the player dropped from; the rest stay a fair coin.
# Bounding the number of biased flips (rather than biasing all `rows` flips)
# keeps the worst-case EV across every multiplier table safely under 1.0 even
# at maximum drag - see plinko/tests.py::test_bias_worst_case_ev_stays_safe
# for the verification. Biasing every row instead would let a player push
# several tables well past 100% RTP with only a few points of shift.
BIAS_ROWS = 2
MAX_BIAS = 0.18

# Each table has `rows + 1` symmetric slots, indexed by slot_index = count of
# "right" bounces (a Binomial(rows, 0.5) distribution: edges rare/high-payout,
# center common/low-payout). Verified via exact binomial EV calculation to
# land in the ~89-97% RTP band (2.9%-10.3% house edge) - see plinko/tests.py::
# test_multiplier_table_expected_values for the regression guard.
MULTIPLIER_TABLES = {
    8: {
        'low':    [5.49, 2.06, 1.08, 0.98, 0.49, 0.98, 1.08, 2.06, 5.49],
        'medium': [12.4, 2.85, 1.24, 0.67, 0.38, 0.67, 1.24, 2.85, 12.4],
        'high':   [26.3, 3.63, 1.36, 0.27, 0.18, 0.27, 1.36, 3.63, 26.3],
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
