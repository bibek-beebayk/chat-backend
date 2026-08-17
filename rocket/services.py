"""
Rollin Rocket round engine.

Architecture note (why there is no server-side timer/loop): the multiplier
is a pure function of elapsed wall-clock time since the round's
`started_at` (see multiplier_at_elapsed below), and the crash point is
generated once, up front, and stored hidden on the round row. This means
the authoritative state of a round at any instant is always computable
on-demand from `now() - started_at` - nothing needs to "tick" in the
background. Every entry point that can observe or act on a round
(polling for live state, an explicit cash-out, a fresh page load after a
refresh) re-derives the current multiplier itself, inside a
transaction.atomic + select_for_update() lock on the round row, and
lazily resolves it (to crashed, or to an auto-cashout) if elapsed time
means it already should have ended. This is what makes "handle latency
safely" and "restore an active round after reconnecting" fall out for
free rather than needing special-cased handling: there is only ever one
source of truth (elapsed time vs. the stored crash point), checked fresh
on every request.
"""

import math
import secrets
from datetime import timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from games.models import Game
from points.services import credit_balance, debit_balance
from .constants import (
    ACCEL_EXPONENT,
    COUNTDOWN_SECONDS,
    GAME_SLUG,
    GAME_VERSION,
    GROWTH_RATE,
    HOUSE_EDGE,
    INSTANT_CRASH_PROBABILITY,
    MAX_CRASH_MULTIPLIER,
)
from .models import RocketRound

_rng = secrets.SystemRandom()


class RocketGameUnavailable(Exception):
    pass


class ActiveRoundExists(Exception):
    def __init__(self, round_obj):
        self.round_obj = round_obj
        super().__init__('An active Rollin Rocket round already exists for this user.')


class NoActiveRound(Exception):
    pass


class TooEarlyToCashOut(Exception):
    pass


class RoundAlreadyResolved(Exception):
    def __init__(self, round_obj):
        self.round_obj = round_obj
        super().__init__('This Rollin Rocket round has already been resolved.')


# ---------------------------------------------------------------------------
# Pure math - crash-point generation and the multiplier growth curve.
# ---------------------------------------------------------------------------

def generate_crash_point(rng=None):
    """
    Securely choose this round's (hidden) crash point. See constants.py for
    the full derivation/rationale of the formula and its RTP property.
    """
    rng = rng or _rng
    if rng.random() < float(INSTANT_CRASH_PROBABILITY):
        return Decimal('1.00')

    r = rng.random()  # uniform [0, 1)
    raw = (Decimal('1') - HOUSE_EDGE) / (Decimal('1') - Decimal(repr(r)))
    crash = raw.quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    if crash < Decimal('1.00'):
        crash = Decimal('1.00')
    if crash > MAX_CRASH_MULTIPLIER:
        crash = MAX_CRASH_MULTIPLIER
    return crash


def multiplier_at_elapsed(elapsed_seconds):
    """
    elapsed_seconds: Decimal seconds since the round's started_at.
    <= 0 means still in the pre-launch countdown - returns 1.00. Strictly
    increasing for t > 0 by construction (e^(k*t^p), k,p > 0), which is
    what makes "current_multiplier >= crash_point" a safe, monotonic
    crash-detection check regardless of how late a check happens to run.
    """
    if elapsed_seconds <= 0:
        return Decimal('1.00')
    t = float(elapsed_seconds)
    exponent = float(GROWTH_RATE) * (t ** float(ACCEL_EXPONENT))
    value = math.exp(exponent)
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_DOWN)


# ---------------------------------------------------------------------------
# Round lifecycle.
# ---------------------------------------------------------------------------

@transaction.atomic
def place_bet(user, *, wager_amount, auto_cashout_multiplier=None, client_request_id=''):
    """
    Returns (round, created) - created=False means client_request_id
    matched an existing round (already placed, not re-charged).
    """
    if client_request_id:
        existing = RocketRound.objects.filter(user=user, client_request_id=client_request_id).first()
        if existing:
            return existing, False

    game = Game.objects.filter(slug=GAME_SLUG).first()
    if not game or not game.is_active:
        raise RocketGameUnavailable()

    # debit_balance() locks (select_for_update) the user's PointsBalance
    # row, which - since two concurrent "place a bet" requests for the
    # SAME user necessarily contend for that same row - is what actually
    # serializes this whole function against itself. The active-round
    # check below therefore only needs to run *after* this call to be
    # race-free: a second concurrent request blocks here until the first
    # has fully committed (round row included), so by the time it reaches
    # the check, the first round is already visible. Raising afterwards
    # rolls back this debit too (whole function is one atomic block), so a
    # rejected duplicate request never leaves a stray charge.
    balance, ledger_entry = debit_balance(
        user,
        amount=wager_amount,
        metadata={'game': GAME_SLUG, 'game_version': GAME_VERSION},
        note=f'Rollin Rocket play ({GAME_VERSION})',
    )

    existing_active = (
        RocketRound.objects
        .select_for_update()
        .filter(user=user, status=RocketRound.STATUS_ACTIVE)
        .first()
    )
    if existing_active:
        raise ActiveRoundExists(existing_active)

    crash_point = generate_crash_point()
    started_at = timezone.now() + timedelta(seconds=float(COUNTDOWN_SECONDS))

    try:
        round_obj = RocketRound.objects.create(
            user=user,
            game=game,
            game_version=GAME_VERSION,
            wager_amount=wager_amount,
            auto_cashout_multiplier=auto_cashout_multiplier,
            crash_point=crash_point,
            started_at=started_at,
            debit_ledger_entry=ledger_entry,
            balance_after=balance.balance,
            client_request_id=client_request_id,
        )
    except IntegrityError:
        # Lost a genuine concurrent race on the same client_request_id
        # (the active-round race is already closed above). Rolling back
        # here undoes the debit too - the view layer re-fetches and
        # returns the winner, same pattern as slots.services.play_round.
        raise

    return round_obj, True


def _elapsed_seconds(round_obj, now):
    return Decimal(str((now - round_obj.started_at).total_seconds()))


def _settle_crash(round_obj, *, now):
    round_obj.status = RocketRound.STATUS_CRASHED
    round_obj.payout_amount = Decimal('0.00')
    round_obj.resolved_at = now
    round_obj.save(update_fields=['status', 'payout_amount', 'resolved_at'])
    _run_post_resolution_hooks(round_obj)


def _settle_cashout(round_obj, *, at_multiplier, now):
    payout_amount = (round_obj.wager_amount * at_multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    balance, ledger_entry = credit_balance(
        round_obj.user,
        amount=payout_amount,
        metadata={
            'game': GAME_SLUG,
            'rocket_round_id': round_obj.id,
            'cashout_multiplier': str(at_multiplier),
        },
        note=f'Rollin Rocket cashout ({GAME_VERSION})',
    )
    round_obj.status = RocketRound.STATUS_CASHED_OUT
    round_obj.cashout_multiplier = at_multiplier
    round_obj.payout_amount = payout_amount
    round_obj.balance_after = balance.balance
    round_obj.credit_ledger_entry = ledger_entry
    round_obj.resolved_at = now
    round_obj.save(update_fields=[
        'status', 'cashout_multiplier', 'payout_amount', 'balance_after',
        'credit_ledger_entry', 'resolved_at',
    ])
    _run_post_resolution_hooks(round_obj)


def _resolve_if_needed(round_obj, *, now):
    """
    Caller must already hold a select_for_update() lock on round_obj. No-op
    unless the round is still active AND elapsed time means it should have
    ended by now (naturally crashed, or crossed its auto-cashout target).
    """
    if round_obj.status != RocketRound.STATUS_ACTIVE:
        return round_obj

    elapsed = _elapsed_seconds(round_obj, now)
    if elapsed <= 0:
        return round_obj  # still counting down, rocket hasn't launched

    current_multiplier = multiplier_at_elapsed(elapsed)

    auto_target = round_obj.auto_cashout_multiplier
    if auto_target is not None and auto_target < round_obj.crash_point and current_multiplier >= auto_target:
        # The auto-cashout threshold is, by construction, reached earlier
        # in elapsed time than the crash point whenever it's below it - so
        # even if this check runs late enough that current_multiplier has
        # also passed crash_point, the player is credited at their chosen
        # target, not penalized for lazy-resolution timing.
        _settle_cashout(round_obj, at_multiplier=auto_target, now=now)
    elif current_multiplier >= round_obj.crash_point:
        _settle_crash(round_obj, now=now)

    return round_obj


@transaction.atomic
def get_current_round(user, *, now=None):
    """
    The player's current in-flight round, lazily resolved against elapsed
    server time before being returned. Returns None if there is nothing
    active (a fresh page load with no round in flight shows the betting
    UI; a round that already resolved on a previous check is not returned
    again here - see history_view for past results). This same function
    backs both the live polling endpoint and "restore on reconnect".
    """
    round_obj = (
        RocketRound.objects
        .select_for_update()
        .filter(user=user, status=RocketRound.STATUS_ACTIVE)
        .first()
    )
    if not round_obj:
        return None
    return _resolve_if_needed(round_obj, now=now or timezone.now())


@transaction.atomic
def cash_out(user, *, now=None):
    """
    Explicit player-initiated cash-out. Always re-derives the authoritative
    multiplier from elapsed server time at this exact instant - the
    frontend's displayed multiplier is never trusted or accepted as input.
    select_for_update() means a second, concurrent cash-out request for the
    same user blocks until the first commits, then finds the round no
    longer active and raises RoundAlreadyResolved instead of double-paying.
    """
    round_obj = (
        RocketRound.objects
        .select_for_update()
        .filter(user=user, status=RocketRound.STATUS_ACTIVE)
        .first()
    )
    if not round_obj:
        last = RocketRound.objects.filter(user=user).order_by('-created_at').first()
        if last:
            raise RoundAlreadyResolved(last)
        raise NoActiveRound()

    now = now or timezone.now()
    elapsed = _elapsed_seconds(round_obj, now)
    if elapsed <= 0:
        raise TooEarlyToCashOut()

    current_multiplier = multiplier_at_elapsed(elapsed)
    if current_multiplier >= round_obj.crash_point:
        _settle_crash(round_obj, now=now)
        raise RoundAlreadyResolved(round_obj)

    _settle_cashout(round_obj, at_multiplier=current_multiplier, now=now)
    return round_obj


def _run_post_resolution_hooks(round_obj):
    from . import xp_hooks
    xp_hooks.grant_rocket_xp(round_obj)
