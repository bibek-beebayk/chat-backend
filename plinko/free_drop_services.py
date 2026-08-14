import secrets
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from games.models import Game
from points.services import settle_wager
from .free_drop_constants import (
    FREE_DROP_BIAS_ROWS,
    FREE_DROP_MAX_BIAS,
    GAME_SLUG,
    get_free_drop_multiplier_table,
)
from .models import PlinkoRound
from .services import GameUnavailable

_rng = secrets.SystemRandom()


def generate_free_drop_path(rows, drop_position=0.0):
    """
    Same bounded-bias-rows model as plinko.services.generate_path, but here
    drop_position is the live, primary mechanic instead of a dead legacy
    field - only the first FREE_DROP_BIAS_ROWS bounces are shifted toward
    the side the player dropped from, the rest stay a fair 50/50 coin.
    """
    position = max(-1.0, min(1.0, drop_position))
    biased_p = 0.5 + position * FREE_DROP_MAX_BIAS
    return [
        1 if _rng.random() < (biased_p if i < FREE_DROP_BIAS_ROWS else 0.5) else 0
        for i in range(rows)
    ]


@transaction.atomic
def play_free_drop_round(user, *, rows, risk_level, wager_amount, drop_position=0.0):
    game = Game.objects.filter(slug=GAME_SLUG).first()
    if not game or not game.is_active:
        raise GameUnavailable()

    position = max(-1.0, min(1.0, drop_position))
    path = generate_free_drop_path(rows, position)
    slot_index = sum(path)
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
            # Decimal isn't JSON-serializable by default (plain JSONField,
            # not DjangoJSONEncoder) - stringify like multiplier above.
            'wager_amount': str(wager_amount),
            'payout_amount': str(payout_amount),
        },
        note=f'Plinko Free Drop round: {rows} rows, {risk_level} risk, drop {position:+.2f}, landed slot {slot_index} (x{multiplier})',
    )

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
        path=path,
        drop_offset=0.0,
        drop_position=position,
        balance_after=balance.balance,
        ledger_entry=ledger_entry,
    )
