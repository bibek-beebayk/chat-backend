"""
Rollin 3x3 slot math engine.

RTP derivation (why the constants.py PAYTABLE/REEL_STRIPS values were
chosen): the server picks one stop per reel uniformly at random via
secrets.SystemRandom().randrange(len(strip)). For a fixed payline, the
symbol shown at whichever row that line reads from a given reel is a
uniform draw over that reel's strip multiset regardless of which of the
3 window rows (top/mid/bottom) the line uses - a uniformly random stop
means every strip position is equally likely, and the row offset is just
a fixed relabeling of the same uniform distribution. So for any one
payline, P(payline shows 3-of-a-kind of symbol X) = product over the 3
reels of (count of X in that reel's strip / strip length), independent of
which row pattern the line uses.

Expectation is additive regardless of correlation between lines (all 5
lines are evaluated against the same 3 stops, so they are correlated, but
E[total] = sum of E[each line] always holds). With all 3 reels sharing the
same symbol-count distribution:

    RTP = num_paylines * sum_over_symbols( (count_X / strip_len) ** 3 * paytable[X] )

This is the exact formula (not an approximation) used to hand-derive the
starting PAYTABLE/REEL_STRIPS values before running the empirical
simulator (slots/management/commands/simulate_slot_rtp.py) to confirm hit
rate/volatility/payout distribution, which the closed-form above cannot
capture on its own.
"""

import secrets
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from games.models import Game
from points.services import settle_wager
from .constants import GAME_SLUG, GAME_VERSION, PAYLINES, PAYTABLE, REEL_STRIPS
from .models import SlotRound

_rng = secrets.SystemRandom()


class SlotGameUnavailable(Exception):
    pass


def spin_reel_stops():
    """Securely choose one stop index per reel. Source of truth for the round."""
    return [_rng.randrange(len(strip)) for strip in REEL_STRIPS]


def derive_grid(stops):
    """
    grid[reel][row] = symbol id, row 0 = top, 1 = middle (the stop itself),
    2 = bottom, taken from the 3 strip positions adjacent to the stop
    (wrapping around the strip, which is logically circular on a real reel).
    """
    grid = []
    for reel_index, stop in enumerate(stops):
        strip = REEL_STRIPS[reel_index]
        n = len(strip)
        top = strip[(stop - 1) % n]
        middle = strip[stop % n]
        bottom = strip[(stop + 1) % n]
        grid.append([top, middle, bottom])
    return grid


def evaluate_paylines(grid):
    """
    A line wins only on an exact 3-of-a-kind match (no wilds/scatters/partial
    wins in v1). Returns (winning_lines, total_multiplier) where
    winning_lines is a list of {line_index, symbol, multiplier} dicts, in
    payline order, and total_multiplier is the Decimal sum of every winning
    line's multiplier (a spin may win on multiple lines simultaneously).
    """
    winning_lines = []
    total_multiplier = Decimal('0')
    for line_index, row_pattern in enumerate(PAYLINES):
        symbols_on_line = [grid[reel][row_pattern[reel]] for reel in range(3)]
        if symbols_on_line[0] == symbols_on_line[1] == symbols_on_line[2]:
            symbol = symbols_on_line[0]
            multiplier = PAYTABLE[symbol]
            winning_lines.append({
                'line_index': line_index,
                'symbol': symbol,
                'multiplier': str(multiplier),
            })
            total_multiplier += multiplier
    return winning_lines, total_multiplier


@transaction.atomic
def play_round(user, *, wager_amount, client_request_id=''):
    """
    Returns (round, created) - created=False means client_request_id matched
    an existing round and that round was replayed rather than re-spun/charged.
    """
    if client_request_id:
        existing = SlotRound.objects.filter(user=user, client_request_id=client_request_id).first()
        if existing:
            return existing, False

    game = Game.objects.filter(slug=GAME_SLUG).first()
    if not game or not game.is_active:
        raise SlotGameUnavailable()

    stops = spin_reel_stops()
    grid = derive_grid(stops)
    winning_lines, total_multiplier = evaluate_paylines(grid)
    payout_amount = (Decimal(wager_amount) * total_multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # winning_lines' per-line payout is informational (total_multiplier/
    # payout_amount above are what's actually settled) - compute it after
    # total payout is known so line payouts sum exactly to payout_amount
    # even with rounding.
    for entry in winning_lines:
        line_multiplier = Decimal(entry['multiplier'])
        entry['payout'] = str((Decimal(wager_amount) * line_multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    metadata = {
        'game_version': GAME_VERSION,
        'reel_stops': stops,
        'winning_lines': winning_lines,
    }

    balance, ledger_entry = settle_wager(
        user,
        wager_amount=wager_amount,
        payout_amount=payout_amount,
        metadata=metadata,
        note=f'Rollin 3x3 slot spin ({GAME_VERSION})',
    )

    net_result = payout_amount - wager_amount
    balance_before = balance.balance - net_result

    # If two requests with the same client_request_id both pass the
    # pre-check above (a genuine race, not just a sequential retry), this
    # create() raises IntegrityError on the unique constraint. Since this
    # whole function runs inside @transaction.atomic, letting that
    # propagate rolls back settle_wager's balance/ledger changes too - the
    # loser is left exactly as if it never ran. The view layer re-fetches
    # and returns the winner's round (same pattern as points.services
    # .award_points's idempotency-key race handling).
    round_obj = SlotRound.objects.create(
        user=user,
        game=game,
        game_version=GAME_VERSION,
        wager_amount=wager_amount,
        reel_1_stop=stops[0],
        reel_2_stop=stops[1],
        reel_3_stop=stops[2],
        grid_snapshot=grid,
        winning_lines=winning_lines,
        total_multiplier=total_multiplier,
        payout_amount=payout_amount,
        net_result=net_result,
        balance_before=balance_before,
        balance_after=balance.balance,
        ledger_entry=ledger_entry,
        client_request_id=client_request_id,
    )
    return round_obj, True
