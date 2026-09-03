from django.utils import timezone

from xp.models import XPAction
from xp.services import ChallengeNotYetEligible, DailyCapExceeded, award_xp
from .constants import CASHOUT_ACHIEVEMENT_THRESHOLDS, STREAK_ACHIEVEMENT_LENGTHS
from .models import HiLoRound


def grant_hilo_xp(round_obj):
    """
    Called once, right after a HiLoRound resolves (bust or cash-out) - see
    hilo/services.py::_settle_bust/_settle_cashout. Reuses the centralized
    XP/challenge system (xp.services.award_xp) rather than hardcoding any
    reward logic here - every award below is just a slug + idempotency key,
    so staff can retune XP values or wire up new challenges against these
    same slugs via the admin without touching this file.

    Every award is best-effort: DailyCapExceeded / ChallengeNotYetEligible /
    XPAction.DoesNotExist are routine, expected conditions that must never
    propagate and roll back the wallet settlement this is called after -
    mirrors rocket/xp_hooks.py and plinko/xp_hooks.py exactly.
    """
    user = round_obj.user

    # Shared cross-game action - Hi-Lo rounds transparently count toward any
    # existing "play N rounds" challenge keyed off it, no duplication needed.
    try:
        award_xp(
            user, 'qualified_gameplay',
            idempotency_key=f'qualified_gameplay:hilo:{round_obj.id}',
            note='Qualified gameplay (Rollin Hi-Lo)',
        )
    except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
        pass

    # Hi-Lo-specific counterpart - lets staff configure a "play Hi-Lo X
    # times" challenge purely via admin config, with no code change here.
    try:
        award_xp(
            user, 'hilo_qualified_gameplay',
            idempotency_key=f'hilo_qualified_gameplay:{round_obj.id}',
            note='Qualified gameplay (Rollin Hi-Lo)',
        )
    except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
        pass

    # Uncapped, zero-XP per-round counter for "play N rounds" challenges -
    # qualified_gameplay is capped at 25/day (XP trickle) and can't back a
    # higher target. Mirrors plinko/rocket. See xp migration 0004.
    try:
        award_xp(
            user, 'gameplay_round',
            idempotency_key=f'gameplay_round:hilo:{round_obj.id}',
            note='Gameplay round (Rollin Hi-Lo)',
        )
    except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
        pass

    try:
        award_xp(
            user, 'daily_challenge_rounds',
            idempotency_key=f'daily_challenge_rounds:{user.id}:{timezone.localdate().isoformat()}',
            note='Daily challenge: play rounds (Rollin Hi-Lo)',
        )
    except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
        pass

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
