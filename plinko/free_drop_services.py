import secrets
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from games.models import Game
from points.services import settle_wager
from .free_drop_constants import (
    GAME_SLUG,
    bucket_index_for_drop_position,
    get_free_drop_multiplier_table,
    get_physics_table,
)
from .models import PlinkoRound
from .services import GameUnavailable

_rng = secrets.SystemRandom()


def pick_free_drop_outcome(rows, drop_position):
    """
    Chooses (bucket_index, slot_index, physics_seed) for a Free Drop round.

    This is the entire outcome model - there is no abstract random-walk
    layered on top. `drop_position` only ever selects which bucket of the
    offline-verified physics distribution to draw from (see
    FREE_DROP_PHYSICS_TABLE in free_drop_constants.py); the slot is then
    sampled from that bucket's real empirical weights, and the physics_seed
    is a real seed that was actually observed to land in that slot from
    that bucket's spawn x. A slot never observed reachable from a bucket
    simply isn't a key in that bucket's table and can never be picked -
    nothing is invented or borrowed from a neighboring bucket.
    """
    bucket_index = bucket_index_for_drop_position(drop_position)
    table = get_physics_table(rows, bucket_index)
    slots = list(table.keys())
    weights = [table[slot]['weight'] for slot in slots]
    slot_index = _rng.choices(slots, weights=weights, k=1)[0]
    physics_seed = _rng.choice(table[slot_index]['seeds'])
    return bucket_index, slot_index, physics_seed


@transaction.atomic
def play_free_drop_round(user, *, rows, risk_level, wager_amount, drop_position=0.0):
    game = Game.objects.filter(slug=GAME_SLUG).first()
    if not game or not game.is_active:
        raise GameUnavailable()

    position = max(-1.0, min(1.0, drop_position))
    _bucket_index, slot_index, physics_seed = pick_free_drop_outcome(rows, position)
    multiplier = Decimal(str(get_free_drop_multiplier_table(rows, risk_level)[slot_index]))
    payout_amount = (Decimal(wager_amount) * multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    balance, ledger_entry = settle_wager(
        user,
        wager_amount=wager_amount,
        payout_amount=payout_amount,
        metadata={
            'game': GAME_SLUG,
            'mode': PlinkoRound.MODE_FREE_DROP,
            'rows': rows,
            'risk_level': risk_level,
            'slot_index': slot_index,
            'multiplier': str(multiplier),
            'drop_position': str(position),
            'physics_seed': physics_seed,
            # Decimal isn't JSON-serializable by default (plain JSONField,
            # not DjangoJSONEncoder) - stringify like multiplier above.
            'wager_amount': str(wager_amount),
            'payout_amount': str(payout_amount),
        },
        note=f'Plinko Free Drop round: {rows} rows, {risk_level} risk, drop {position:+.2f}, landed slot {slot_index} (x{multiplier})',
    )

    # Gameplay/challenge XP fires automatically from settle_wager() above -
    # see points.services._grant_round_xp. Nothing Plinko-specific needed here.

    return PlinkoRound.objects.create(
        user=user,
        game=game,
        mode=PlinkoRound.MODE_FREE_DROP,
        rows=rows,
        risk_level=risk_level,
        wager_amount=wager_amount,
        slot_index=slot_index,
        multiplier=multiplier,
        payout_amount=payout_amount,
        # Free Drop has no bounce-path model anymore (see
        # pick_free_drop_outcome) - the round's reproducible state is
        # drop_position + physics_seed instead.
        path=[],
        drop_offset=0.0,
        drop_position=position,
        physics_seed=physics_seed,
        balance_after=balance.balance,
        ledger_entry=ledger_entry,
    )
