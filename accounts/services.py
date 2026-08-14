from django.db import transaction
from django.utils import timezone
from points.services import award_points
from xp.models import XPAction
from xp.services import ChallengeNotYetEligible, DailyCapExceeded, award_xp


def grant_daily_login_rewards(user):
    """
    Daily-login is XP-only (+10 XP once per calendar day) - the doc's
    Reward Point earning activity list (registration/backfill/referral/
    games/admin adjustments) does not include daily login, so no RP is
    granted here, unlike grant_registration_rewards().

    Safe to call from any login path (password or Google) - self-guards on
    user_type and swallows expected/config errors so a login can never be
    blocked by the reward system.
    """
    if getattr(user, 'user_type', None) != 'player':
        return
    idempotency_key = f'daily_login:{user.id}:{timezone.localdate().isoformat()}'
    try:
        award_xp(user, 'daily_login', idempotency_key=idempotency_key, note='Daily login')
    except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible) as exc:
        import logging
        logging.getLogger(__name__).error('Daily login XP grant failed for user %s: %s', user.id, exc)


def grant_registration_rewards(user):
    """
    Grants the one-time registration bonus (1000 RP + 10 XP) as a single
    atomic pair - either both land or neither does, so a misconfigured
    PointAction/XPAction (or any other mid-operation failure) can never
    leave a user with RP but no XP or vice versa. RP is awarded before XP
    (consistent lock ordering if this pattern is ever reused elsewhere).

    Idempotent: reuses the same idempotency key across both ledgers -
    safe, since the uniqueness constraint is scoped per-app/per-action, and
    it makes the two grants trivially correlatable in the ledgers.

    Callers must invoke this AFTER the core account-activation write
    (user.is_active = True / user.save()) has already committed, and must
    catch its own exceptions locally - a reward-system config error must
    never block account creation/activation.
    """
    idempotency_key = f'registration:{user.id}'
    with transaction.atomic():
        award_points(user, 'registration_bonus', idempotency_key=idempotency_key, note='Registration bonus')
        award_xp(user, 'registration', idempotency_key=idempotency_key, note='Registration XP')
