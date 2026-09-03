from xp.models import XPAction
from xp.services import ChallengeNotYetEligible, DailyCapExceeded, award_xp
from .constants import CASHOUT_ACHIEVEMENT_THRESHOLDS, STREAK_ACHIEVEMENT_LENGTHS
from .models import HiLoRound


def grant_hilo_xp(round_obj):
    """
    Called once, right after a HiLoRound resolves (bust or cash-out) - see
    hilo/services.py::_settle_bust/_settle_cashout.

    Gameplay/challenge XP for just having played a round (qualified_gameplay,
    hilo_qualified_gameplay, gameplay_round, hilo_gameplay_round, and any
    challenges sourced on them) fires automatically at bet-placement time
    from points.services._grant_round_xp, not from here - see
    hilo/services.py::start_round's call to debit_balance(). What's left
    here is purely resolution-specific: streaks and cashout thresholds can
    only be known once the round has actually ended.

    Every award below is still just a slug + idempotency key - staff can
    retune XP values or wire up new challenges against them via admin
    without touching this file. Every award is best-effort:
    DailyCapExceeded / ChallengeNotYetEligible / XPAction.DoesNotExist are
    routine, expected conditions that must never propagate and roll back
    the wallet settlement this is called after.
    """
    user = round_obj.user

    # Streak awards are read straight off the round. Where Rocket's "Five
    # Alive" had to walk round history to reconstruct a streak, a Hi-Lo
    # streak lives *within* one round and is already a persisted field -
    # and it's awarded on bust as well as cash-out, since a long streak the
    # player then lost is still a streak they achieved.
    for length in STREAK_ACHIEVEMENT_LENGTHS:
        if round_obj.streak < length:
            continue
        slug = f'hilo_streak_{length}'
        try:
            award_xp(
                user, slug,
                idempotency_key=f'{slug}:{round_obj.id}',
                note=f'Rollin Hi-Lo: {length}-card streak',
            )
        except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
            pass

    if round_obj.status != HiLoRound.STATUS_CASHED_OUT:
        return

    for threshold in CASHOUT_ACHIEVEMENT_THRESHOLDS:
        if round_obj.multiplier < threshold:
            continue
        slug = f'hilo_cashout_above_{int(threshold)}x'
        try:
            award_xp(
                user, slug,
                idempotency_key=f'{slug}:{round_obj.id}',
                note=f'Rollin Hi-Lo cashout above {threshold}x',
            )
        except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
            pass
