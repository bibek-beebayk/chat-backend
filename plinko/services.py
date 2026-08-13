import secrets
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from games.models import Game
from points.services import settle_wager
from .constants import BIAS_ROWS, GAME_SLUG, MAX_BIAS, get_multiplier_table
from .models import PlinkoRound


class GameUnavailable(Exception):
    pass


_rng = secrets.SystemRandom()


def generate_path(rows, drop_offset=0.0):
    """
    Returns a list of `rows` ints: 0 = left bounce, 1 = right bounce.

    Only the first BIAS_ROWS bounces have their probability shifted toward
    the side the player dropped from (drop_offset in [-1, 1]); the rest stay
    a fair 50/50 coin. See constants.py for why this is bounded rather than
    biasing every row.
    """
    offset = max(-1.0, min(1.0, drop_offset))
    biased_p = 0.5 + offset * MAX_BIAS
    return [
        1 if _rng.random() < (biased_p if i < BIAS_ROWS else 0.5) else 0
        for i in range(rows)
    ]


@transaction.atomic
def play_round(user, *, rows, risk_level, wager_amount, drop_offset=0.0):
    game = Game.objects.filter(slug=GAME_SLUG).first()
    if not game or not game.is_active:
        raise GameUnavailable()

    offset = max(-1.0, min(1.0, drop_offset))
    path = generate_path(rows, offset)
    slot_index = sum(path)
    multiplier = Decimal(str(get_multiplier_table(rows, risk_level)[slot_index]))
    payout_amount = int(
        (Decimal(wager_amount) * multiplier).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    )

    balance, ledger_entry = settle_wager(
        user,
        wager_amount=wager_amount,
        payout_amount=payout_amount,
        metadata={
            'game': GAME_SLUG,
            'rows': rows,
            'risk_level': risk_level,
            'slot_index': slot_index,
            'multiplier': str(multiplier),
            'wager_amount': wager_amount,
            'payout_amount': payout_amount,
        },
        note=f'Plinko round: {rows} rows, {risk_level} risk, landed slot {slot_index} (x{multiplier})',
    )

    return PlinkoRound.objects.create(
        user=user,
        game=game,
        rows=rows,
        risk_level=risk_level,
        wager_amount=wager_amount,
        slot_index=slot_index,
        multiplier=multiplier,
        payout_amount=payout_amount,
        path=path,
        drop_offset=offset,
        balance_after=balance.balance,
        ledger_entry=ledger_entry,
    )
