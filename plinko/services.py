import secrets
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from games.models import Game
from points.services import settle_wager
from .constants import BIAS_ROWS, GAME_SLUG, MAX_BIAS, get_multiplier_table
from .models import PlinkoRound
from .xp_hooks import grant_gameplay_xp


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

    # drop_offset is still accepted, clamped, stored, and echoed back for API
    # backwards compatibility, but no longer feeds into path generation - the
    # drag-to-bias mechanic it powered was replaced by a fixed center drop
    # when the board moved to real Matter.js physics (which has no concept
    # of a drop position at all), so honoring a client-supplied value here
    # would just reopen an EV-exploitable path with no product benefit.
    # generate_path() itself still supports biasing (see test coverage in
    # tests.py) in case this ever needs to be reactivated deliberately.
    offset = max(-1.0, min(1.0, drop_offset))
    path = generate_path(rows, 0.0)
    slot_index = sum(path)
    multiplier = Decimal(str(get_multiplier_table(rows, risk_level)[slot_index]))
    payout_amount = (Decimal(wager_amount) * multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

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
            # Decimal isn't JSON-serializable by default (plain JSONField,
            # not DjangoJSONEncoder) - stringify like multiplier above.
            # wager_amount is normally a plain int (the API only ever passes
            # 5 or 10), but play_round() is a general service function and a
            # caller can legitimately pass a Decimal (e.g. a partial-balance
            # wager), so stringify defensively rather than assuming the type.
            'wager_amount': str(wager_amount),
            'payout_amount': str(payout_amount),
        },
        note=f'Plinko round: {rows} rows, {risk_level} risk, landed slot {slot_index} (x{multiplier})',
    )

    grant_gameplay_xp(user, ledger_entry)

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
