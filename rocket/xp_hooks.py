from xp.models import XPAction
from xp.services import ChallengeNotYetEligible, DailyCapExceeded, award_xp
from .constants import CASHOUT_ACHIEVEMENT_THRESHOLDS, FIVE_ALIVE_STREAK_LENGTH
from .models import RocketRound


def grant_rocket_xp(round_obj):
    """
    Called once, right after a RocketRound resolves (crash or cash-out) -
    see rocket/services.py::_settle_crash/_settle_cashout.

    Gameplay/challenge XP for just having played a round (qualified_gameplay,
    rocket_qualified_gameplay, gameplay_round, rocket_gameplay_round, and
    any challenges sourced on them) fires automatically at bet-placement
    time from points.services._grant_round_xp, not from here - see
    rocket/services.py::place_bet's call to debit_balance(). What's left
    here is purely resolution-specific: it can only be known once the
    round has actually ended.

    Every award below is still just a slug + idempotency key - staff can
    retune XP values or wire up new challenges against them via admin
    without touching this file. Every award is best-effort:
    DailyCapExceeded/ChallengeNotYetEligible/XPAction.DoesNotExist are
    routine, expected conditions that must never propagate and roll back
    the wallet settlement this is called after.
    """
    user = round_obj.user

    if round_obj.status != RocketRound.STATUS_CASHED_OUT:
        return

    _update_five_alive_streak(user)

    cashout = round_obj.cashout_multiplier
    for threshold in CASHOUT_ACHIEVEMENT_THRESHOLDS:
        if cashout < threshold:
            continue
        slug = f'rocket_cashout_above_{int(threshold)}x'
        key = f'{slug}:{round_obj.id}'
        try:
            award_xp(user, slug, idempotency_key=key, note=f'Rollin Rocket cashout above {threshold}x')
        except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
            pass


def _update_five_alive_streak(user):
    """
    "Five Alive" - N consecutive successful cash-outs in a row, computed by
    walking the user's most recent resolved rounds (most recent first)
    rather than a dedicated streak-counter field - simple and correct at
    the round volumes this game sees, and avoids another piece of mutable
    per-user state to keep in sync with the round history.

    Also doubles as the reusable hook for "highest Rocket cashout" /
    "highest Rocket multiplier this week" style future achievements -
    those need no new hook at all, since RocketRound already persists
    cashout_multiplier and created_at for every resolved round; a future
    feature can query them directly (e.g. ordering by -cashout_multiplier,
    or filtering created_at__gte=start_of_week) without any change here.
    """
    recent = list(
        RocketRound.objects
        .filter(user=user, status__in=[RocketRound.STATUS_CASHED_OUT, RocketRound.STATUS_CRASHED])
        .order_by('-created_at')[:FIVE_ALIVE_STREAK_LENGTH]
    )
    if len(recent) < FIVE_ALIVE_STREAK_LENGTH:
        return
    if not all(r.status == RocketRound.STATUS_CASHED_OUT for r in recent):
        return

    latest = recent[0]
    try:
        award_xp(
            user, 'rocket_five_alive',
            idempotency_key=f'rocket_five_alive:{latest.id}',
            note='Five Alive: 5 consecutive successful Rollin Rocket cash-outs',
        )
    except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
        pass
