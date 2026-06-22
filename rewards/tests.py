from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import LoginStreakEntry, StreakRedemptionRequest
from .services import clear_streak_after_redemption, record_daily_visit


class LoginStreakRedemptionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='streak-player',
            email='streak-player@example.com',
            password='test-pass-123',
            user_type='player',
        )

    def _record_visit_on(self, visit_date):
        with patch('rewards.services.timezone.localdate', return_value=visit_date):
            return record_daily_visit(self.user)

    def test_completed_redemption_starts_a_fresh_streak_window(self):
        first_day = date(2026, 6, 1)
        for offset in range(7):
            streak = self._record_visit_on(first_day + timedelta(days=offset))

        self.assertEqual(streak.current_streak, 7)
        self.assertEqual(streak.receivable_bonus, Decimal('5.00'))
        self.assertEqual(LoginStreakEntry.objects.filter(user=self.user).count(), 7)

        StreakRedemptionRequest.objects.create(
            user=self.user,
            amount=Decimal('5.00'),
            hi_rollin_username='hi-rollin-player',
            status=StreakRedemptionRequest.STATUS_COMPLETED,
            completed_at=timezone.make_aware(datetime(2026, 6, 7, 12, 0)),
        )
        clear_streak_after_redemption(self.user)

        same_day_streak = self._record_visit_on(date(2026, 6, 7))
        self.assertEqual(same_day_streak.current_streak, 0)
        self.assertEqual(same_day_streak.receivable_bonus, Decimal('0.00'))

        next_day_streak = self._record_visit_on(date(2026, 6, 8))
        self.assertEqual(next_day_streak.current_streak, 1)
        self.assertEqual(next_day_streak.receivable_bonus, Decimal('0.00'))
        self.assertEqual(LoginStreakEntry.objects.filter(user=self.user).count(), 8)
