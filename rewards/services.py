from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import LoginStreak, LoginStreakEntry, STREAK_REWARD_AMOUNT, STREAK_TARGET_DAYS


@transaction.atomic
def record_daily_visit(user):
    if not user or getattr(user, 'user_type', None) != 'player':
        return None

    today = timezone.localdate()
    streak, _ = LoginStreak.objects.select_for_update().get_or_create(user=user)
    created_entry = LoginStreakEntry.objects.get_or_create(user=user, login_date=today)[1]

    if not created_entry:
        return streak

    previous_date = streak.last_login_date
    if previous_date == today - timedelta(days=1):
        streak.current_streak += 1
    else:
        streak.current_streak = 1

    streak.last_login_date = today

    if streak.current_streak >= STREAK_TARGET_DAYS and streak.receivable_bonus < STREAK_REWARD_AMOUNT:
        streak.receivable_bonus = Decimal(STREAK_REWARD_AMOUNT)
        streak.last_awarded_at = timezone.now()

    streak.save(update_fields=['current_streak', 'last_login_date', 'receivable_bonus', 'last_awarded_at', 'updated_at'])
    return streak


@transaction.atomic
def clear_streak_after_redemption(user):
    streak, _ = LoginStreak.objects.select_for_update().get_or_create(user=user)
    streak.current_streak = 0
    streak.last_login_date = None
    streak.receivable_bonus = Decimal('0.00')
    streak.last_awarded_at = None
    streak.save(update_fields=['current_streak', 'last_login_date', 'receivable_bonus', 'last_awarded_at', 'updated_at'])
    return streak
