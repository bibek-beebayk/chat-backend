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


def _validate_physics_table(table):
    """
    Structural sanity check run once at import time, so a malformed or
    truncated table.json fails Django startup loudly instead of surfacing
    as a confusing runtime error (or worse, an inconsistent round) the
    first time a player hits a bad entry. This can't re-verify that a seed
    actually reproduces its claimed slot (that requires Matter.js, which
    only exists in the JS/TS generator - see
    scripts/generate-free-drop-physics-table.ts's own re-simulation pass
    for that check) - this only validates the data's shape and internal
    consistency.
    """
    for rows, buckets in table.items():
        if not isinstance(rows, int) or rows < 1:
            raise ValueError(f'free_drop_physics_table.json: invalid rows key {rows!r}')
        if len(buckets) != DROP_BUCKETS:
            raise ValueError(
                f'free_drop_physics_table.json: rows={rows} has {len(buckets)} buckets, expected {DROP_BUCKETS}'
            )
        for bucket_index, slots in buckets.items():
            if not (0 <= bucket_index < DROP_BUCKETS):
                raise ValueError(f'free_drop_physics_table.json: rows={rows} bucket index {bucket_index} out of range')
            if not slots:
                raise ValueError(f'free_drop_physics_table.json: rows={rows} bucket={bucket_index} has no reachable slots')
            total_weight = 0.0
            for slot_index, entry in slots.items():
                if not (0 <= slot_index <= rows):
                    raise ValueError(
                        f'free_drop_physics_table.json: rows={rows} bucket={bucket_index} slot {slot_index} out of range [0, {rows}]'
                    )
                seeds = entry.get('seeds')
                weight = entry.get('weight')
                if not seeds or not all(isinstance(s, int) for s in seeds):
                    raise ValueError(
                        f'free_drop_physics_table.json: rows={rows} bucket={bucket_index} slot={slot_index} has an empty/invalid seeds list'
                    )
                if not isinstance(weight, (int, float)) or not (0 < weight <= 1):
                    raise ValueError(
                        f'free_drop_physics_table.json: rows={rows} bucket={bucket_index} slot={slot_index} has invalid weight {weight!r}'
                    )
                total_weight += weight
            if not (0 < total_weight <= 1.0001):
                raise ValueError(
                    f'free_drop_physics_table.json: rows={rows} bucket={bucket_index} weights sum to {total_weight}, expected in (0, 1]'
                )
    return table


FREE_DROP_PHYSICS_TABLE = _validate_physics_table({
    int(rows): {
        int(bucket): {
            int(slot): entry
            for slot, entry in slots.items()
        }
        for bucket, slots in buckets.items()
    }
    for rows, buckets in _raw_physics_table.items()
})


def get_physics_table(rows, bucket_index):
    return FREE_DROP_PHYSICS_TABLE[rows][bucket_index]


# NOT Classic's shape - deliberately different, and for a real reason.
# Classic's edge slots are its jackpot tier because a fair coin-flip walk
# makes them rare (~0.4% at 8 rows). Free Drop breaks that assumption: a
# player can aim directly at an edge and the real physics table above shows
# that's the single MOST reliable slot to hit (well over 50% from the
# matching extreme bucket) - so pricing edges as a jackpot here would hand out a
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
# Re-derived (same alpha/ceiling-search method, see git history for the
# derivation script) after the spawn-x jitter fix changed the physics
# engine's actual reachability distribution - these values are only valid
# together with the free_drop_physics_table.json they were fit against.
FREE_DROP_MULTIPLIER_TABLES = {
    8: {
        'low':    [0.26, 1.06, 1.10, 1.17, 1.30, 1.17, 1.10, 1.06, 0.26],
        'medium': [0.06, 0.98, 1.05, 1.17, 1.45, 1.17, 1.05, 0.98, 0.06],
        'high':   [0.01, 0.84, 0.94, 1.13, 1.59, 1.13, 0.94, 0.84, 0.01],
    },
}


def get_free_drop_multiplier_table(rows, risk_level):
    return FREE_DROP_MULTIPLIER_TABLES[rows][risk_level]


def get_pegs_per_row(rows):
    return PEGS_PER_ROW[rows]
