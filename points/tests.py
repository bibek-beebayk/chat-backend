from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import PointAction, PointsBalance, PointsLedgerEntry, PointsRedemptionConfig, PointsRedemptionRequest
from .services import (
    ActiveRedemptionExists,
    BelowMinimumRedemption,
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
        # These tests exercise balance/hold/refund/completion logic with
        # small numbers - the redemption-minimum feature has its own
        # dedicated tests below (with realistic 5000+ values), so keep the
        # minimum low here to avoid entangling the two concerns. The
        # migration seed already created the pk=1 singleton row, so update
        # it in place rather than .objects.create() (which forces an
        # INSERT and would collide with that existing row).
        config = PointsRedemptionConfig.get_solo()
        config.min_redemption_points = 1
        config.save()

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


class RedemptionConfigTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='redeem-player',
            email='redeem-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.action = PointAction.objects.create(
            slug='big_grant',
            label='Big Grant',
            points_value=10000,
            is_active=True,
        )

    def test_get_solo_recreates_default_config_if_missing(self):
        # In a real deploy the seed migration always creates this row first,
        # but get_solo() must still be safe to call if it's ever missing.
        PointsRedemptionConfig.objects.all().delete()
        self.assertEqual(PointsRedemptionConfig.objects.count(), 0)
        config = PointsRedemptionConfig.get_solo()
        self.assertEqual(config.min_redemption_points, 5000)
        self.assertEqual(PointsRedemptionConfig.objects.count(), 1)

    def test_singleton_always_uses_pk_1(self):
        config = PointsRedemptionConfig(min_redemption_points=7000)
        config.save()
        self.assertEqual(config.pk, 1)
        config2 = PointsRedemptionConfig(min_redemption_points=8000)
        config2.save()
        self.assertEqual(PointsRedemptionConfig.objects.count(), 1)
        self.assertEqual(PointsRedemptionConfig.objects.get().min_redemption_points, 8000)

    def test_below_minimum_redemption_is_rejected(self):
        award_points(self.user, self.action.slug)  # balance = 10000
        with self.assertRaises(BelowMinimumRedemption):
            create_redemption_request(self.user, 4999)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 10000)
        self.assertEqual(PointsRedemptionRequest.objects.count(), 0)

    def test_exact_minimum_redemption_is_accepted(self):
        award_points(self.user, self.action.slug)
        redemption_request = create_redemption_request(self.user, 5000)
        self.assertEqual(redemption_request.points_amount, 5000)

    def test_conversion_rate_is_snapshotted_and_survives_later_rate_changes(self):
        config = PointsRedemptionConfig.get_solo()
        config.min_redemption_points = 5000
        config.rp_to_credit_rate = Decimal('2.5000')
        config.save()
        award_points(self.user, self.action.slug)
        redemption_request = create_redemption_request(self.user, 5000)
        self.assertEqual(redemption_request.conversion_rate_snapshot, Decimal('2.5000'))
        self.assertEqual(redemption_request.hi_rollin_credit_amount, Decimal('12500.00'))

        # Changing the live rate afterward must not alter the historical request.
        config = PointsRedemptionConfig.get_solo()
        config.rp_to_credit_rate = Decimal('9.0000')
        config.save()
        redemption_request.refresh_from_db()
        self.assertEqual(redemption_request.conversion_rate_snapshot, Decimal('2.5000'))


class PointsInfoViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username='info-player',
            email='info-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.url = reverse('points-info')

    def test_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)

    def test_returns_current_redemption_config(self):
        config = PointsRedemptionConfig.get_solo()
        config.min_redemption_points = 3000
        config.rp_to_credit_rate = Decimal('1.5000')
        config.save()

        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.data['data'] if 'data' in response.data else response.data
        self.assertEqual(data['min_redemption_points'], 3000)
        self.assertEqual(data['rp_to_credit_rate'], '1.5000')

    def test_only_visible_active_actions_are_included(self):
        PointAction.objects.create(
            slug='visible_bonus', label='Visible Bonus', points_value=500,
            is_active=True, is_visible_to_players=True,
        )
        PointAction.objects.create(
            slug='hidden_backfill', label='Hidden Backfill', points_value=1000,
            is_active=True, is_visible_to_players=False,
        )
        PointAction.objects.create(
            slug='inactive_bonus', label='Inactive Bonus', points_value=250,
            is_active=False, is_visible_to_players=True,
        )

        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        data = response.data['data'] if 'data' in response.data else response.data
        slugs = [item['slug'] for item in data['earn_actions']]
        self.assertIn('visible_bonus', slugs)
        self.assertNotIn('hidden_backfill', slugs)
        self.assertNotIn('inactive_bonus', slugs)

    def test_seeded_backfill_action_is_hidden_from_players(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        data = response.data['data'] if 'data' in response.data else response.data
        slugs = [item['slug'] for item in data['earn_actions']]
        self.assertNotIn('registration_backfill_2026_08', slugs)


class PointsBalanceViewTests(TestCase):
    """
    Regression coverage for the bug where the player-facing rewards page
    called listRedemptions() (staff-only) alongside getBalance() in one
    Promise.all - the resulting 403 rejected the whole batch, so balance
    silently rendered as 0.00 even though the real balance was fine.
    balance_view must never depend on staff-only endpoints, and must expose
    the player's own active redemption request directly.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username='balance-player',
            email='balance-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.action = PointAction.objects.create(
            slug='balance_test_bonus', label='Balance Test Bonus', points_value=6000, is_active=True,
        )
        self.url = reverse('points-balance')

    def test_player_can_load_own_balance_without_staff_access(self):
        award_points(self.user, self.action.slug)
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.data['data'] if 'data' in response.data else response.data
        self.assertEqual(data['balance'], '6000.00')
        self.assertEqual(data['lifetime_earned'], 6000)
        self.assertIsNone(data['active_redemption_request'])

    def test_active_redemption_request_is_own_request_only(self):
        award_points(self.user, self.action.slug)
        other_user = get_user_model().objects.create_user(
            username='other-balance-player',
            email='other-balance-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        award_points(other_user, self.action.slug)
        create_redemption_request(other_user, 6000)
        redemption = create_redemption_request(self.user, 6000)

        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        data = response.data['data'] if 'data' in response.data else response.data
        self.assertIsNotNone(data['active_redemption_request'])
        self.assertEqual(data['active_redemption_request']['id'], redemption.id)
        self.assertEqual(data['active_redemption_request']['status'], 'pending')

    def test_redemption_list_view_remains_staff_only(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(reverse('points-redemptions'))
        self.assertEqual(response.status_code, 403)
