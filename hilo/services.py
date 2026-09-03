"""
Rollin Hi-Lo round engine.

Architecture note (why this is simpler than Rocket): a Hi-Lo round has no
time dimension. Rocket's multiplier is a function of elapsed wall-clock
time, so every entry point there has to lazily re-derive and resolve the
round against `now()`. Here a round only ever changes when the player acts,
so there is nothing to resolve on read - `get_current_round` is a plain
fetch, and the only mutation points are start/predict/cash-out.

What that leaves is the same concurrency discipline as Rocket: every
mutation takes a select_for_update() lock on the round row inside
transaction.atomic, wallet movement goes through points.services, and
duplicate requests are absorbed rather than double-charged
(client_request_id on start, step_index on predict, "already resolved" on
cash-out).

Fairness note: the next card does not exist until the predict request
arrives - it is generated with secrets.SystemRandom inside the locked
transaction and immediately recorded on a HiLoStep row. There is no hidden
pre-committed outcome for a client to guess at (a stronger position than
Rocket's hidden crash_point), and the quoted odds the client displays are
recomputed here from the same formula on every request, never trusted as
input.
"""

import secrets
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from games.models import Game
from points.services import credit_balance, debit_balance
from .constants import (
    GAME_SLUG,
    GAME_VERSION,
    HOUSE_EDGE,
    MAX_MULTIPLIER,
    MAX_PAYOUT,
    MAX_STEPS,
    MIN_STEP_MULTIPLIER,
    RANK_COUNT,
    RANK_VALUES,
    RANKS,
    SUITS,
)
from .models import HiLoRound, HiLoStep

_rng = secrets.SystemRandom()

TWO_PLACES = Decimal('0.01')


class HiLoGameUnavailable(Exception):
    pass


class ActiveRoundExists(Exception):
    def __init__(self, round_obj):
        self.round_obj = round_obj
        super().__init__('An active Rollin Hi-Lo round already exists for this user.')


class NoActiveRound(Exception):
    pass


class StaleStep(Exception):
    """
    The client predicted against a step index the round has already moved
    past - a duplicate click or a retried request. Carries the
    authoritative round so the caller can replay current state instead of
    drawing another card.
    """

    def __init__(self, round_obj):
        self.round_obj = round_obj
        super().__init__('This prediction has already been resolved.')


class ImpossiblePrediction(Exception):
    """LOWER on a 2, or HIGHER on an ace - can never win, only push or lose."""

    def __init__(self, direction):
        self.direction = direction
        super().__init__(f'{direction.upper()} is not possible from this card.')


class NothingToCashOut(Exception):
    """Cash-out attempted at 1.00x, before any correct prediction."""


class RoundAlreadyResolved(Exception):
    def __init__(self, round_obj):
        self.round_obj = round_obj
        super().__init__('This Rollin Hi-Lo round has already been resolved.')


# ---------------------------------------------------------------------------
# Pure math - card generation, probabilities, and the payout curve.
# These functions touch no database and are unit-tested in isolation.
# ---------------------------------------------------------------------------

def draw_card(rng=None):
    """
    One independently generated card. Not dealt from a depleting deck (see
    constants.py) - so the probabilities below are stateless, and the quote
    shown on a button is always exactly the probability used to price it.
    """
    rng = rng or _rng
    return {'rank': rng.choice(RANKS), 'suit': rng.choice(SUITS)}


def rank_value(rank):
    """2..14, ace high."""
    return RANK_VALUES[rank]


def outcome_counts(rank):
    """
    How many of the 13 ranks are higher than / lower than / equal to `rank`.
    Counts rather than probabilities so callers can divide once, at the
    precision they need, without compounding rounding.
    """
    value = rank_value(rank)
    higher = 14 - value
    lower = value - 2
    return {'higher': higher, 'lower': lower, 'push': 1}


def probability(rank, direction):
    """Raw probability of `direction` winning outright (pushes excluded)."""
    return Decimal(outcome_counts(rank)[direction]) / Decimal(RANK_COUNT)


def push_probability():
    return Decimal(1) / Decimal(RANK_COUNT)


def step_multiplier(rank, direction, *, house_edge=HOUSE_EDGE):
    """
    The multiplier a correct `direction` call from `rank` pays.

    A push returns the round to an equivalent state - same accumulated
    multiplier, a new face-up card, a fresh quote - so a prediction is
    settled entirely by the non-push branch. Conditioning on it:

        p_effective = count_dir / (count_higher + count_lower)   # = /12
        step        = (1 / p_effective) * (1 - house_edge)

    which yields a flat (1 - house_edge) expected return on every single
    prediction, whatever the card or direction. Quantized ROUND_DOWN so
    rounding never favours the player, then clamped to MIN_STEP_MULTIPLIER
    (see constants.py for why that floor exists).

    Raises ImpossiblePrediction where the direction can never win.
    """
    counts = outcome_counts(rank)
    count = counts[direction]
    if count == 0:
        raise ImpossiblePrediction(direction)

    non_push = Decimal(counts['higher'] + counts['lower'])
    raw = (non_push / Decimal(count)) * (Decimal(1) - house_edge)
    step = raw.quantize(TWO_PLACES, rounding=ROUND_DOWN)
    return max(step, MIN_STEP_MULTIPLIER)


def quote(rank, *, house_edge=HOUSE_EDGE):
    """
    Both sides of the current card, as the prediction buttons display them.
    An impossible direction is reported with `available: False` and a null
    multiplier rather than omitted, so the client can render it disabled in
    place instead of reflowing the controls.
    """
    counts = outcome_counts(rank)
    sides = {}
    for direction in ('higher', 'lower'):
        available = counts[direction] > 0
        sides[direction] = {
            'available': available,
            'probability': str(probability(rank, direction).quantize(Decimal('0.0001'))),
            'multiplier': str(step_multiplier(rank, direction, house_edge=house_edge)) if available else None,
        }
    sides['push_probability'] = str(push_probability().quantize(Decimal('0.0001')))
    return sides


def evaluate(from_rank, to_rank, direction):
    """win / push / loss for one prediction."""
    from_value, to_value = rank_value(from_rank), rank_value(to_rank)
    if to_value == from_value:
        return HiLoStep.OUTCOME_PUSH
    went_higher = to_value > from_value
    correct = went_higher if direction == HiLoStep.PREDICTION_HIGHER else not went_higher
    return HiLoStep.OUTCOME_WIN if correct else HiLoStep.OUTCOME_LOSS


def apply_step(multiplier, step):
    """Accumulate one winning step, quantized down and clamped to the cap."""
    combined = (multiplier * step).quantize(TWO_PLACES, rounding=ROUND_DOWN)
    return min(combined, MAX_MULTIPLIER)


def payout_for(wager_amount, multiplier):
    """
    What `multiplier` is worth on `wager_amount`, under both ceilings. The
    multiplier cap and the payout cap are independent knobs - MAX_MULTIPLIER
    alone on a max wager would expose a 100,000-point single-round payout.
    """
    payout = (wager_amount * multiplier).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return min(payout, MAX_PAYOUT)


def is_capped(round_obj):
    """Has this round hit a ceiling that force-ends it (design spec s16)?"""
    return (
        round_obj.multiplier >= MAX_MULTIPLIER
        or round_obj.steps_taken >= MAX_STEPS
        or payout_for(round_obj.wager_amount, round_obj.multiplier) >= MAX_PAYOUT
    )


# ---------------------------------------------------------------------------
# Round lifecycle.
# ---------------------------------------------------------------------------

@transaction.atomic
def start_round(user, *, wager_amount, client_request_id=''):
    """
    Returns (round, created) - created=False means client_request_id matched
    an existing round (already started, not re-charged).
    """
    if client_request_id:
        existing = HiLoRound.objects.filter(user=user, client_request_id=client_request_id).first()
        if existing:
            return existing, False

    game = Game.objects.filter(slug=GAME_SLUG).first()
    if not game or not game.is_active:
        raise HiLoGameUnavailable()

    # debit_balance() locks (select_for_update) the user's PointsBalance
    # row, which - since two concurrent "start a round" requests for the
    # SAME user necessarily contend for that row - is what serializes this
    # whole function against itself. The active-round check below therefore
    # only needs to run *after* this call to be race-free. Raising
    # afterwards rolls back this debit too (one atomic block), so a
    # rejected duplicate never leaves a stray charge. Same reasoning as
    # rocket.services.place_bet.
    balance, ledger_entry = debit_balance(
        user,
        amount=wager_amount,
        metadata={'game': GAME_SLUG, 'game_version': GAME_VERSION},
        note=f'Rollin Hi-Lo play ({GAME_VERSION})',
    )

    existing_active = (
        HiLoRound.objects
        .select_for_update()
        .filter(user=user, status=HiLoRound.STATUS_ACTIVE)
        .first()
    )
    if existing_active:
        raise ActiveRoundExists(existing_active)

    card = draw_card()
    return HiLoRound.objects.create(
        user=user,
        game=game,
        game_version=GAME_VERSION,
        wager_amount=wager_amount,
        current_rank=card['rank'],
        current_suit=card['suit'],
        multiplier=Decimal('1.00'),
        debit_ledger_entry=ledger_entry,
        balance_after=balance.balance,
        client_request_id=client_request_id,
    ), True


def get_current_round(user):
    """
    The player's in-flight round, or None. A plain read - unlike Rocket
    there is nothing to lazily resolve, since a Hi-Lo round never changes
    on its own. Backs both the "restore after refresh" mount call and the
    409 response body when a duplicate start is rejected.
    """
    return HiLoRound.objects.filter(user=user, status=HiLoRound.STATUS_ACTIVE).first()


@transaction.atomic
def predict(user, *, direction, step_index):
    """
    Resolve one Higher/Lower call. Returns (round, step).

    `step_index` is the client's claim about which prediction it is making -
    it must equal the round's current steps_taken. A duplicate click or a
    retried request therefore arrives stale and raises StaleStep *before*
    any card is drawn, which is how "a player cannot predict twice for one
    card" is enforced; select_for_update serializes everything else, and
    HiLoStep's unique_together backs it at the DB level.
    """
    round_obj = (
        HiLoRound.objects
        .select_for_update()
        .filter(user=user, status=HiLoRound.STATUS_ACTIVE)
        .first()
    )
    if not round_obj:
        last = HiLoRound.objects.filter(user=user).order_by('-created_at').first()
        if last:
            raise RoundAlreadyResolved(last)
        raise NoActiveRound()

    if step_index != round_obj.steps_taken:
        raise StaleStep(round_obj)

    # Raises ImpossiblePrediction for LOWER on a 2 / HIGHER on an ace. Done
    # before the draw so a rejected request consumes no randomness and
    # leaves the round exactly as it was.
    step_value = step_multiplier(round_obj.current_rank, direction)

    from_rank, from_suit = round_obj.current_rank, round_obj.current_suit
    next_card = draw_card()
    outcome = evaluate(from_rank, next_card['rank'], direction)

    if outcome == HiLoStep.OUTCOME_WIN:
        round_obj.multiplier = apply_step(round_obj.multiplier, step_value)
        round_obj.streak += 1
    # A push leaves multiplier and streak untouched but still advances the
    # card - the player chooses again from the new one, re-quoted.

    round_obj.steps_taken += 1
    # Both a win and a push advance the face-up card. On a loss it is left
    # as the losing card for the result screen; the round is over either way.
    if outcome != HiLoStep.OUTCOME_LOSS:
        round_obj.current_rank = next_card['rank']
        round_obj.current_suit = next_card['suit']

    step = HiLoStep.objects.create(
        round=round_obj,
        step_index=step_index,
        from_rank=from_rank,
        from_suit=from_suit,
        prediction=direction,
        to_rank=next_card['rank'],
        to_suit=next_card['suit'],
        outcome=outcome,
        step_multiplier=step_value if outcome == HiLoStep.OUTCOME_WIN else Decimal('1.00'),
        multiplier_after=round_obj.multiplier,
    )

    if outcome == HiLoStep.OUTCOME_LOSS:
        _settle_bust(round_obj)
        return round_obj, step

    round_obj.save(update_fields=['multiplier', 'streak', 'steps_taken', 'current_rank', 'current_suit'])

    if is_capped(round_obj):
        # Ceiling reached - the server ends the round itself and pays out
        # rather than leaving a live round the player can't act on.
        _settle_cashout(round_obj, capped=True)

    return round_obj, step


@transaction.atomic
def cash_out(user):
    """
    Explicit player-initiated cash-out. select_for_update means a second,
    concurrent request blocks until the first commits, then finds the round
    no longer active and raises RoundAlreadyResolved instead of double-
    paying - the view returns the same final state either way, so a
    duplicate click is idempotent rather than an error.
    """
    round_obj = (
        HiLoRound.objects
        .select_for_update()
        .filter(user=user, status=HiLoRound.STATUS_ACTIVE)
        .first()
    )
    if not round_obj:
        last = HiLoRound.objects.filter(user=user).order_by('-created_at').first()
        if last:
            raise RoundAlreadyResolved(last)
        raise NoActiveRound()

    # Cashing out at 1.00x would just hand the wager back; the design spec
    # gates cash-out on at least one correct prediction.
    if round_obj.multiplier <= Decimal('1.00'):
        raise NothingToCashOut()

    _settle_cashout(round_obj, capped=False)
    return round_obj


def _settle_bust(round_obj):
    round_obj.status = HiLoRound.STATUS_BUSTED
    round_obj.payout_amount = Decimal('0.00')
    round_obj.resolved_at = timezone.now()
    round_obj.save(update_fields=[
        'status', 'payout_amount', 'resolved_at',
        'multiplier', 'streak', 'steps_taken', 'current_rank', 'current_suit',
    ])
    _run_post_resolution_hooks(round_obj)


def _settle_cashout(round_obj, *, capped):
    payout_amount = payout_for(round_obj.wager_amount, round_obj.multiplier)
    balance, ledger_entry = credit_balance(
        round_obj.user,
        amount=payout_amount,
        metadata={
            'game': GAME_SLUG,
            'hilo_round_id': round_obj.id,
            'multiplier': str(round_obj.multiplier),
            'capped': capped,
        },
        note=f'Rollin Hi-Lo cashout ({GAME_VERSION})',
    )
    round_obj.status = HiLoRound.STATUS_CASHED_OUT
    round_obj.capped = capped
    round_obj.payout_amount = payout_amount
    round_obj.balance_after = balance.balance
    round_obj.credit_ledger_entry = ledger_entry
    round_obj.resolved_at = timezone.now()
    round_obj.save(update_fields=[
        'status', 'capped', 'payout_amount', 'balance_after',
        'credit_ledger_entry', 'resolved_at',
    ])
    _run_post_resolution_hooks(round_obj)


def _run_post_resolution_hooks(round_obj):
    from . import xp_hooks
    xp_hooks.grant_hilo_xp(round_obj)
