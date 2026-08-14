from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import (
    LoginStreak,
    LoginStreakEntry,
    StreakRedemptionRequest,
    STREAK_REWARD_AMOUNT,
    STREAK_TARGET_DAYS,
)
from xp.models import XPAction
from xp.services import ChallengeNotYetEligible, DailyCapExceeded, award_xp


def _reset_streak(streak):
    streak.current_streak = 0
    streak.last_login_date = None
    streak.receivable_bonus = Decimal('0.00')
    streak.last_awarded_at = None


def _latest_completed_redemption_date(user):
    completed_at = (
        StreakRedemptionRequest.objects
        .filter(
            user=user,
            status=StreakRedemptionRequest.STATUS_COMPLETED,
            completed_at__isnull=False,
        )
        .order_by('-completed_at')
        .values_list('completed_at', flat=True)
        .first()
    )
    if not completed_at:
        return None
    return timezone.localtime(completed_at).date()


def _count_consecutive_entries(user, end_date, after_date=None):
    streak_count = 0
    cursor = end_date
    if after_date and cursor <= after_date:
        return streak_count
    while LoginStreakEntry.objects.filter(user=user, login_date=cursor).exists():
        streak_count += 1
        cursor -= timedelta(days=1)
        if after_date and cursor <= after_date:
            break
    return streak_count


@transaction.atomic
def record_daily_visit(user):
    if not user or getattr(user, 'user_type', None) != 'player':
        return None

    today = timezone.localdate()
    streak, _ = LoginStreak.objects.select_for_update().get_or_create(user=user)
    LoginStreakEntry.objects.get_or_create(user=user, login_date=today)

    reset_after_date = _latest_completed_redemption_date(user)
    streak.current_streak = _count_consecutive_entries(user, today, after_date=reset_after_date)
    streak.last_login_date = today if not reset_after_date or today > reset_after_date else None

    if streak.current_streak < STREAK_TARGET_DAYS:
        streak.receivable_bonus = Decimal('0.00')
        streak.last_awarded_at = None

    if streak.current_streak >= STREAK_TARGET_DAYS and streak.receivable_bonus < STREAK_REWARD_AMOUNT:
        streak.receivable_bonus = Decimal(STREAK_REWARD_AMOUNT)
        streak.last_awarded_at = timezone.now()
        # XP-only (see xp/migrations/0002_seed_xp_actions.py's streak_7day
        # action) - this is a SEPARATE reward from the Hi-Rollin-paid-out
        # StreakRedemptionRequest bonus above; don't conflate the two.
        # Reuses this block's own cycle-boundary guard (current_streak just
        # crossed the target AND hasn't already been credited this cycle)
        # rather than re-deriving that transition elsewhere.
        try:
            award_xp(
                user, 'streak_7day',
                idempotency_key=f'streak_7day:{user.id}:{today.isoformat()}',
                note='7-day login streak',
            )
        except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
            pass

    streak.save(update_fields=['current_streak', 'last_login_date', 'receivable_bonus', 'last_awarded_at', 'updated_at'])
    return streak


@transaction.atomic
def expire_stale_streak(user, reference_date=None):
    streak, _ = LoginStreak.objects.select_for_update().get_or_create(user=user)
    reset_after_date = _latest_completed_redemption_date(user)
    if reset_after_date and (streak.last_login_date is None or streak.last_login_date <= reset_after_date):
        if streak.current_streak or streak.receivable_bonus or streak.last_awarded_at:
            _reset_streak(streak)
            streak.save(update_fields=['current_streak', 'last_login_date', 'receivable_bonus', 'last_awarded_at', 'updated_at'])
        return streak

    today = reference_date or timezone.localdate()
    if streak.last_login_date and streak.last_login_date < today - timedelta(days=1):
        _reset_streak(streak)
        streak.save(update_fields=['current_streak', 'last_login_date', 'receivable_bonus', 'last_awarded_at', 'updated_at'])
    return streak


@transaction.atomic
def clear_streak_after_redemption(user):
    streak, _ = LoginStreak.objects.select_for_update().get_or_create(user=user)
    _reset_streak(streak)
    streak.save(update_fields=['current_streak', 'last_login_date', 'receivable_bonus', 'last_awarded_at', 'updated_at'])
    return streak
