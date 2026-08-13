from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import PointAction, PointsBalance, PointsLedgerEntry, PointsRedemptionRequest
from .services import (
    ActiveRedemptionExists,
    DailyCapExceeded,
    InsufficientPoints,
    apply_adjustment,
    award_points,
    create_redemption_request,
    review_redemption_request,
    settle_wager,
)


class PointsServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='points-player',
            email='points-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.staff = get_user_model().objects.create_user(
            username='points-staff',
            email='points-staff@example.com',
            password='test-pass-123',
            user_type='staff',
        )
        self.action = PointAction.objects.create(
            slug='daily_login',
            label='Daily Login Bonus',
            points_value=10,
            is_active=True,
        )

    def test_award_points_increments_balance_and_lifetime_earned(self):
        award_points(self.user, self.action.slug)
        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 10)
        self.assertEqual(balance.lifetime_earned, 10)
        self.assertEqual(
            PointsLedgerEntry.objects.filter(user=self.user, entry_type=PointsLedgerEntry.ENTRY_EARN).count(),
            1,
        )

    def test_award_points_is_idempotent(self):
        award_points(self.user, self.action.slug, idempotency_key='session-1')
        award_points(self.user, self.action.slug, idempotency_key='session-1')
        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 10)
        self.assertEqual(
            PointsLedgerEntry.objects.filter(user=self.user, idempotency_key='session-1').count(),
            1,
        )

    def test_award_points_respects_daily_cap(self):
        self.action.max_awards_per_day = 1
        self.action.save(update_fields=['max_awards_per_day'])

        award_points(self.user, self.action.slug)
        with self.assertRaises(DailyCapExceeded):
            award_points(self.user, self.action.slug)

        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 10)

    def test_create_redemption_request_fails_with_insufficient_points(self):
        with self.assertRaises(InsufficientPoints):
            create_redemption_request(self.user, 10)

    def test_create_redemption_request_reserves_points_and_blocks_second_active_request(self):
        award_points(self.user, self.action.slug)
        award_points(self.user, self.action.slug)  # balance now 20

        redemption_request = create_redemption_request(self.user, 10)
        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 10)
        self.assertEqual(redemption_request.status, PointsRedemptionRequest.STATUS_PENDING)
        self.assertEqual(
            PointsLedgerEntry.objects.filter(
                user=self.user, entry_type=PointsLedgerEntry.ENTRY_REDEMPTION_HOLD,
            ).count(),
            1,
        )

        with self.assertRaises(ActiveRedemptionExists):
            create_redemption_request(self.user, 5)

    def test_rejecting_redemption_refunds_points(self):
        award_points(self.user, self.action.slug)
        redemption_request = create_redemption_request(self.user, 10)

        review_redemption_request(redemption_request, self.staff, PointsRedemptionRequest.STATUS_REJECTED, staff_note='not eligible')

        balance = PointsBalance.objects.get(user=self.user)
        self.assertEqual(balance.balance, 10)
        redemption_request.refresh_from_db()
        self.assertEqual(redemption_request.status, PointsRedemptionRequest.STATUS_REJECTED)
        self.assertEqual(
            PointsLedgerEntry.objects.filter(
                user=self.user, entry_type=PointsLedgerEntry.ENTRY_REDEMPTION_REFUND,
            ).count(),
            1,
        )

        # balance was restored, so the user can submit a new request
        create_redemption_request(self.user, 10)

    def test_approve_then_complete_does_not_double_deduct(self):
        award_points(self.user, self.action.slug)
        redemption_request = create_redemption_request(self.user, 10)
        balance_after_hold = PointsBalance.objects.get(user=self.user).balance

        review_redemption_request(redemption_request, self.staff, PointsRedemptionRequest.STATUS_APPROVED)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, balance_after_hold)

        review_redemption_request(redemption_request, self.staff, PointsRedemptionRequest.STATUS_COMPLETED)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, balance_after_hold)

        redemption_request.refresh_from_db()
        self.assertEqual(redemption_request.status, PointsRedemptionRequest.STATUS_COMPLETED)
        self.assertIsNotNone(redemption_request.completed_at)

    def test_pending_request_cannot_be_completed_directly(self):
        award_points(self.user, self.action.slug)
        redemption_request = create_redemption_request(self.user, 10)
        with self.assertRaises(ValueError):
            review_redemption_request(redemption_request, self.staff, PointsRedemptionRequest.STATUS_COMPLETED)

    def test_settle_wager_debits_and_credits_atomically(self):
        award_points(self.user, self.action.slug)  # balance = 10
        balance, entry = settle_wager(self.user, wager_amount=10, payout_amount=35)
        self.assertEqual(balance.balance, 35)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 35)
        self.assertEqual(entry.entry_type, PointsLedgerEntry.ENTRY_GAME_ROUND)
        self.assertEqual(entry.delta, 25)
        self.assertEqual(entry.balance_after, 35)
        self.assertEqual(
            PointsLedgerEntry.objects.filter(user=self.user, entry_type=PointsLedgerEntry.ENTRY_GAME_ROUND).count(),
            1,
        )

    def test_settle_wager_rejects_insufficient_balance_with_no_partial_mutation(self):
        award_points(self.user, self.action.slug)  # balance = 10
        with self.assertRaises(InsufficientPoints):
            settle_wager(self.user, wager_amount=100, payout_amount=0)

        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 10)
        self.assertEqual(
            PointsLedgerEntry.objects.filter(user=self.user, entry_type=PointsLedgerEntry.ENTRY_GAME_ROUND).count(),
            0,
        )

    def test_settle_wager_allows_zero_payout(self):
        award_points(self.user, self.action.slug)  # balance = 10
        balance, entry = settle_wager(self.user, wager_amount=10, payout_amount=0)
        self.assertEqual(balance.balance, 0)
        self.assertEqual(entry.delta, -10)
        self.assertGreaterEqual(PointsBalance.objects.get(user=self.user).balance, 0)

    def test_apply_adjustment_awards_points_and_bumps_lifetime_earned(self):
        balance, entry = apply_adjustment(self.user, self.staff, 250, note='manual grant for testing')
        self.assertEqual(balance.balance, 250)
        self.assertEqual(balance.lifetime_earned, 250)
        self.assertEqual(entry.entry_type, PointsLedgerEntry.ENTRY_ADJUSTMENT)
        self.assertEqual(entry.delta, 250)
        self.assertEqual(entry.awarded_by, self.staff)

    def test_apply_adjustment_can_deduct_without_affecting_lifetime_earned(self):
        apply_adjustment(self.user, self.staff, 100)
        balance, entry = apply_adjustment(self.user, self.staff, -40)
        self.assertEqual(balance.balance, 60)
        self.assertEqual(balance.lifetime_earned, 100)
        self.assertEqual(entry.delta, -40)

    def test_apply_adjustment_rejects_deduction_below_zero(self):
        apply_adjustment(self.user, self.staff, 10)
        with self.assertRaises(InsufficientPoints):
            apply_adjustment(self.user, self.staff, -20)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 10)

    def test_apply_adjustment_rejects_zero_delta(self):
        with self.assertRaises(ValueError):
            apply_adjustment(self.user, self.staff, 0)
