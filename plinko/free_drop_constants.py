import json
from pathlib import Path

# Free Drop is a separate Plinko mode from Classic (see plinko/constants.py) -
# nothing here is read by, or affects, Classic's game logic or tables.

# Only 8 rows for the first implementation, matching Classic's current
# restriction. PEGS_PER_ROW is keyed by rows (not hardcoded) so 12/16 can be
# added later without a rewrite.
FREE_DROP_ROWS_CHOICES = (8,)

# Equal-pegs-per-row board (not triangular). pegsPerRow = rows, not an
# independently chosen number: the ball's landing slot has rows+1 possible
# values (one per divider gap), so the last row's peg count is what has to
# match rows+1 slots, exactly like Classic's triangular board (whose last
# row also has `rows` pegs for the same reason).
PEGS_PER_ROW = {
    8: 8,
}

GAME_SLUG = 'plinko'

# Continuous drop_position is bucketed into this many buckets *only* for
# offline physics search (see scripts/generate-free-drop-physics-table.ts) -
# there's no way to search a fresh distribution for every possible float.
# This is NOT used to snap or substitute the runtime spawn position, which
# always uses the exact continuous drop_position - see
# free_drop_services.py and FreeDropPlinkoCanvas.tsx. Odd so there's a true
# center bucket.
DROP_BUCKETS = 15


def bucket_index_for_drop_position(drop_position):
    """Nearest discrete bucket index for a continuous drop_position - mirrors freeDropPhysics.ts's bucketIndexForDropPosition exactly (same formula, both languages must agree)."""
    clamped = max(-1.0, min(1.0, drop_position))
    t = (clamped + 1) / 2
    return round(t * (DROP_BUCKETS - 1))


def drop_position_for_bucket_index(bucket_index):
    """The exact drop_position a bucket index represents - mirrors freeDropPhysics.ts's dropPositionForBucketIndex."""
    return -1 + (bucket_index / (DROP_BUCKETS - 1)) * 2


# The empirically-verified, physically-reachable outcome distribution:
# rows -> bucket_index -> slot_index -> {"seeds": [...], "weight": float}.
# Generated once offline (real Matter.js simulation, thousands of attempts
# per bucket) by scripts/generate-free-drop-physics-table.ts - see that
# script's header for the full rationale. `weight` is the empirical
# probability of landing that slot from that bucket's exact spawn x; a slot
# absent from a bucket's dict was never observed reachable from there in the
# offline sample and must never be selected for that bucket. This is the
# single source of truth for which slots play_free_drop_round() may choose
# from - there is no other (abstract/random-walk) outcome model for Free
# Drop anymore.
_PHYSICS_TABLE_PATH = Path(__file__).resolve().parent / 'free_drop_physics_table.json'
with open(_PHYSICS_TABLE_PATH) as _f:
    _raw_physics_table = json.load(_f)

FREE_DROP_PHYSICS_TABLE = {
    int(rows): {
        int(bucket): {
            int(slot): entry
            for slot, entry in slots.items()
        }
        for bucket, slots in buckets.items()
    }
    for rows, buckets in _raw_physics_table.items()
}


def get_physics_table(rows, bucket_index):
    return FREE_DROP_PHYSICS_TABLE[rows][bucket_index]


# NOT Classic's shape - deliberately different, and for a real reason.
# Classic's edge slots are its jackpot tier because a fair coin-flip walk
# makes them rare (~0.4% at 8 rows). Free Drop breaks that assumption: a
# player can aim directly at an edge and the real physics table above shows
# that's the single MOST reliable slot to hit (up to ~70% from the matching
# extreme bucket) - so pricing edges as a jackpot here would hand out a
# guaranteed-positive-EV move. The near-center slots are comparatively the
# *least* reliable to guarantee (even aiming right at them, chaos spreads
# the result across neighbors more than an edge drop does), so this table's
# shape is the physics-appropriate inverse of Classic's: modest at the
# edges, highest near (not exactly at) center. Values were derived by
# fitting multiplier ~ 1/reachability^alpha against the REAL empirical
# per-slot peak reachability across every bucket (see
# free_drop_physics_table.json), with alpha increasing per risk tier for
# more spread, then scaling each tier down until the worst-case RTP over
# EVERY bucket in FREE_DROP_PHYSICS_TABLE stays safely under 100% - see
# plinko/tests.py::FreeDropMultiplierTableTests for the regression guard
# that recomputes this against the live data, not a static formula.
FREE_DROP_MULTIPLIER_TABLES = {
    8: {
        'low':    [0.40, 0.83, 0.83, 1.15, 1.15, 1.15, 0.83, 0.83, 0.40],
        'medium': [0.15, 0.64, 0.64, 1.24, 1.24, 1.24, 0.64, 0.64, 0.15],
        'high':   [0.04, 0.46, 0.46, 1.31, 1.31, 1.31, 0.46, 0.46, 0.04],
    },
}


def get_free_drop_multiplier_table(rows, risk_level):
    return FREE_DROP_MULTIPLIER_TABLES[rows][risk_level]


def get_pegs_per_row(rows):
    return PEGS_PER_ROW[rows]
