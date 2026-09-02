from django.utils import timezone
from xp.models import XPAction
from xp.services import ChallengeNotYetEligible, DailyCapExceeded, award_xp


def grant_gameplay_xp(user, ledger_entry):
    """
    Shared "qualified gameplay" + "daily challenge" XP hook, called by both
    Classic (plinko/services.py::play_round) and Free Drop
    (plinko/free_drop_services.py::play_free_drop_round) right after
    settle_wager() succeeds. Any wager size qualifies - the doc doesn't
    distinguish by wager amount, and the daily cap already bounds total
    farmable XP regardless.

    DailyCapExceeded/ChallengeNotYetEligible are routine, expected
    conditions (every round past the cap, every round before the
    challenge's Nth) and must never propagate - doing so would roll back
    the real-money wager settlement this is called from.
    """
    idempotency_key = f'qualified_gameplay:{ledger_entry.id}'
    try:
        award_xp(user, 'qualified_gameplay', idempotency_key=idempotency_key, note='Qualified gameplay')
    except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
        pass

    # Uncapped, zero-XP per-round counter that "play N rounds" challenges count
    # against - qualified_gameplay above is capped at 25/day (its job is the XP
    # trickle) so it can't back a target higher than that. See xp migration 0004.
    round_key = f'gameplay_round:{ledger_entry.id}'
    try:
        award_xp(user, 'gameplay_round', idempotency_key=round_key, note='Gameplay round')
    except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
        pass

    challenge_key = f'daily_challenge_rounds:{user.id}:{timezone.localdate().isoformat()}'
    try:
        award_xp(user, 'daily_challenge_rounds', idempotency_key=challenge_key, note='Daily challenge: play rounds')
    except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
        pass
