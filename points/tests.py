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
    debit_balance,
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


class GenericRoundXPTests(TestCase):
    """
    points.services._grant_round_xp - the generic "a round was played" XP
    signal fired automatically by settle_wager() and debit_balance() below,
    keyed off metadata['game']. This is what a new game gets for free
    (qualified_gameplay + gameplay_round, and its own <slug>_* counterparts
    if seeded) purely by charging a wager the normal way, with no
    xp_hooks.py of its own - see the docstring on _grant_round_xp.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='round-xp-player', email='round-xp-player@example.com',
            password='test-pass-123', user_type='player',
        )
        PointsBalance.objects.create(user=self.user, balance=1000)

    def test_settle_wager_fires_the_two_shared_actions_for_a_new_game(self):
        from xp.models import XPAction
        from xp.models import XPLedgerEntry as XPLedger

        # A game slug with NO per-game XPAction rows seeded at all - proves
        # the shared actions still fire, and the optional per-game ones
        # (fictional_qualified_gameplay / fictional_gameplay_round) are
        # silently skipped rather than erroring.
        settle_wager(self.user, wager_amount=Decimal('10'), payout_amount=Decimal('0'), metadata={'game': 'fictional'})

        self.assertTrue(XPLedger.objects.filter(user=self.user, action__slug='qualified_gameplay').exists())
        self.assertTrue(XPLedger.objects.filter(user=self.user, action__slug='gameplay_round').exists())
        self.assertFalse(XPAction.objects.filter(slug='fictional_gameplay_round').exists())

    def test_debit_balance_fires_the_same_signal_as_settle_wager(self):
        from xp.models import XPLedgerEntry as XPLedger

        debit_balance(self.user, amount=Decimal('10'), metadata={'game': 'fictional'})

        self.assertTrue(XPLedger.objects.filter(user=self.user, action__slug='qualified_gameplay').exists())
        self.assertTrue(XPLedger.objects.filter(user=self.user, action__slug='gameplay_round').exists())

    def test_per_game_counters_fire_when_they_exist(self):
        from xp.models import XPAction
        from xp.models import XPLedgerEntry as XPLedger

        XPAction.objects.create(slug='newgame_gameplay_round', label='New Game Rounds', xp_value=0, is_active=True)

        settle_wager(self.user, wager_amount=Decimal('10'), payout_amount=Decimal('0'), metadata={'game': 'newgame'})

        self.assertTrue(XPLedger.objects.filter(user=self.user, action__slug='newgame_gameplay_round').exists())

    def test_a_challenge_scoped_to_a_brand_new_game_fires_via_the_generic_signal(self):
        """
        The end-to-end promise: create ONE XPAction (the per-game counter)
        plus a challenge sourced on it - entirely in admin/data, no code -
        and a plain settle_wager() call for that game makes it progress.
        """
        from xp.models import XPAction
        from xp.models import XPLedgerEntry as XPLedger

        counter = XPAction.objects.create(slug='indie_gameplay_round', label='Indie Rounds', xp_value=0, is_active=True)
        challenge = XPAction.objects.create(
            slug='indie_daily_challenge', label='Play Indie', xp_value=25, is_active=True,
            challenge_target_count=1,
        )
        challenge.challenge_source_actions.set([counter])

        settle_wager(self.user, wager_amount=Decimal('10'), payout_amount=Decimal('0'), metadata={'game': 'indie'})

        self.assertTrue(XPLedger.objects.filter(user=self.user, action=challenge).exists())

    def test_no_game_in_metadata_awards_nothing(self):
        # A non-gameplay debit (e.g. a manual staff adjustment elsewhere in
        # the codebase) must never be mistaken for a played round.
        from xp.models import XPLedgerEntry as XPLedger

        settle_wager(self.user, wager_amount=Decimal('10'), payout_amount=Decimal('0'), metadata={'note': 'not a game'})

        self.assertFalse(XPLedger.objects.filter(user=self.user).exists())

    def test_a_capped_xp_action_never_blocks_the_wager_settlement(self):
        from xp.models import XPAction
        XPAction.objects.filter(slug='qualified_gameplay').update(max_awards_per_day=0)

        balance, entry = settle_wager(self.user, wager_amount=Decimal('10'), payout_amount=Decimal('5'), metadata={'game': 'fictional'})

        self.assertEqual(balance.balance, Decimal('995'))  # wager still settled despite the capped XP action


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


class BulkPointsAdjustmentAdminTests(TestCase):
    """
    The bulk points adjustment admin action on PointsBalanceAdmin - a
    standard two-step Django admin action (mirrors delete_selected exactly:
    first POST renders a confirmation form, second POST with `apply` set
    actually applies it), which is what gets multi-select and "select all N
    matching your search" for free from Django's own changelist machinery.
    """

    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            username='bulk-points-admin', email='bulk-points-admin@example.com', password='test-pass-123',
        )
        self.client.force_login(self.staff)

        self.u1 = get_user_model().objects.create_user(
            username='bulk-u1', email='bulk-u1@example.com', password='x', user_type='player',
        )
        self.u2 = get_user_model().objects.create_user(
            username='bulk-u2', email='bulk-u2@example.com', password='x', user_type='player',
        )
        self.b1 = PointsBalance.objects.create(user=self.u1, balance=Decimal('100'))
        self.b2 = PointsBalance.objects.create(user=self.u2, balance=Decimal('50'))

    def test_first_post_renders_a_confirmation_page_without_applying_anything(self):
        from django.contrib.admin import helpers
        response = self.client.post('/admin/points/pointsbalance/', data={
            'action': 'bulk_adjust_points',
            helpers.ACTION_CHECKBOX_NAME: [self.b1.pk, self.b2.pk],
            'index': '0',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bulk-u1')
        self.assertContains(response, 'bulk-u2')
        self.assertEqual(PointsLedgerEntry.objects.filter(entry_type=PointsLedgerEntry.ENTRY_ADJUSTMENT).count(), 0)

    def test_second_post_applies_the_same_amount_to_every_selected_user(self):
        from django.contrib.admin import helpers
        response = self.client.post('/admin/points/pointsbalance/', data={
            'action': 'bulk_adjust_points',
            helpers.ACTION_CHECKBOX_NAME: [self.b1.pk, self.b2.pk],
            'apply': '1',
            'points_delta': '1000',
            'note': 'bulk grant test',
        })
        self.assertEqual(response.status_code, 302)  # redirects back to the changelist
        self.b1.refresh_from_db()
        self.b2.refresh_from_db()
        self.assertEqual(self.b1.balance, Decimal('1100'))
        self.assertEqual(self.b2.balance, Decimal('1050'))
        self.assertEqual(PointsLedgerEntry.objects.filter(entry_type=PointsLedgerEntry.ENTRY_ADJUSTMENT).count(), 2)

    def test_select_across_resolves_to_every_user_matching_the_current_search(self):
        # A user that would NOT match a search for 'bulk-u' - proves "select
        # all N matching your search" scopes to the search, not the world.
        other_user = get_user_model().objects.create_user(
            username='unrelated-player', email='unrelated@example.com', password='x', user_type='player',
        )
        PointsBalance.objects.create(user=other_user, balance=Decimal('10'))

        from django.contrib.admin import helpers
        # Mirrors what the admin's own "Select all N matching your search"
        # link actually submits: the current page's checkboxes stay
        # checked AND select_across is set - select_across alone with no
        # checkboxes is not a request Django's changelist view recognizes
        # as "items selected" (see ModelAdmin.changelist_view's own
        # pre-check), so it must be additive, not a replacement.
        response = self.client.post('/admin/points/pointsbalance/?q=bulk-u', data={
            'action': 'bulk_adjust_points',
            'select_across': '1',
            helpers.ACTION_CHECKBOX_NAME: [self.b1.pk, self.b2.pk],
            'index': '0',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bulk-u1')
        self.assertContains(response, 'bulk-u2')
        self.assertNotContains(response, 'unrelated-player')

    def test_a_negative_adjustment_skips_users_it_would_take_below_zero_without_blocking_others(self):
        self.b2.balance = Decimal('5')
        self.b2.save(update_fields=['balance'])

        from django.contrib.admin import helpers
        response = self.client.post('/admin/points/pointsbalance/', data={
            'action': 'bulk_adjust_points',
            helpers.ACTION_CHECKBOX_NAME: [self.b1.pk, self.b2.pk],
            'apply': '1',
            'points_delta': '-50',
            'note': '',
        })
        self.assertEqual(response.status_code, 302)
        self.b1.refresh_from_db()
        self.b2.refresh_from_db()
        self.assertEqual(self.b1.balance, Decimal('50'))  # succeeded
        self.assertEqual(self.b2.balance, Decimal('5'))  # skipped - would go negative, left untouched

    def test_zero_delta_is_rejected_by_the_form_rather_than_silently_no_opping(self):
        from django.contrib.admin import helpers
        response = self.client.post('/admin/points/pointsbalance/', data={
            'action': 'bulk_adjust_points',
            helpers.ACTION_CHECKBOX_NAME: [self.b1.pk],
            'apply': '1',
            'points_delta': '0',
            'note': '',
        })
        self.assertEqual(response.status_code, 200)  # re-renders the form with a validation error
        self.assertContains(response, 'non-zero')
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.balance, Decimal('100'))

    def test_the_single_user_quick_adjust_page_still_works(self):
        # The player field is now a searchable autocomplete (posts the
        # user's pk), not a typed exact username - see PointsAdjustmentForm.
        response = self.client.post('/admin/points/pointsadjustment/', data={
            'user': str(self.u1.pk),
            'points_delta': '25',
            'note': 'still works',
        })
        self.assertEqual(response.status_code, 200)
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.balance, Decimal('125'))


class PointsBalanceAdminVisibilityTests(TestCase):
    """
    PointsBalanceAdmin.get_queryset's self-healing backfill - a player with
    no PointsBalance row (never had a single points event yet) must still
    show up in this admin list, not just players who happen to already
    have one.
    """

    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            username='visibility-admin', email='visibility-admin@example.com', password='test-pass-123',
        )
        self.client.force_login(self.staff)

    def test_a_player_with_no_balance_row_yet_appears_after_visiting_the_list(self):
        player = get_user_model().objects.create_user(
            username='never-earned-anything', email='never-earned@example.com', password='x', user_type='player',
        )
        self.assertFalse(PointsBalance.objects.filter(user=player).exists())

        response = self.client.get('/admin/points/pointsbalance/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'never-earned-anything')
        balance = PointsBalance.objects.get(user=player)
        self.assertEqual(balance.balance, Decimal('0.00'))

    def test_backfilled_players_are_immediately_selectable_for_bulk_adjustment(self):
        player = get_user_model().objects.create_user(
            username='backfill-then-adjust', email='backfill-then-adjust@example.com', password='x', user_type='player',
        )
        # First visit is what creates the row (see get_queryset).
        self.client.get('/admin/points/pointsbalance/')
        balance = PointsBalance.objects.get(user=player)

        from django.contrib.admin import helpers
        response = self.client.post('/admin/points/pointsbalance/', data={
            'action': 'bulk_adjust_points',
            helpers.ACTION_CHECKBOX_NAME: [balance.pk],
            'apply': '1',
            'points_delta': '1000',
            'note': '',
        })
        self.assertEqual(response.status_code, 302)
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('1000.00'))

    def test_staff_accounts_are_not_backfilled(self):
        # PointsBalance is a player-facing concept - a staff account with
        # no row shouldn't spontaneously get one just from viewing this list.
        staff_only = get_user_model().objects.create_user(
            username='staff-no-points', email='staff-no-points@example.com', password='x', user_type='staff',
        )
        self.client.get('/admin/points/pointsbalance/')
        self.assertFalse(PointsBalance.objects.filter(user=staff_only).exists())

    def test_existing_balances_are_left_untouched(self):
        player = get_user_model().objects.create_user(
            username='already-has-balance', email='already-has-balance@example.com', password='x', user_type='player',
        )
        PointsBalance.objects.create(user=player, balance=Decimal('42.00'), lifetime_earned=42)

        self.client.get('/admin/points/pointsbalance/')

        balance = PointsBalance.objects.get(user=player)
        self.assertEqual(balance.balance, Decimal('42.00'))
        self.assertEqual(PointsBalance.objects.filter(user=player).count(), 1)


class PointsAdjustmentSinglePlayerFormTests(TestCase):
    """
    The single-player quick-adjust page's player field - a searchable
    autocomplete instead of a typed exact username. The AJAX search endpoint
    itself is Django admin's standard autocomplete view (backed by
    UserAdmin.search_fields), exercised separately by Django's own test
    suite - what's specific to this form is that only a player can actually
    be submitted, even though the search isn't scoped to players alone.
    """

    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            username='single-adjust-admin', email='single-adjust-admin@example.com', password='test-pass-123',
        )
        self.client.force_login(self.staff)
        self.player = get_user_model().objects.create_user(
            username='single-adjust-player', email='single-adjust-player@example.com', password='x', user_type='player',
        )
        self.other_staff = get_user_model().objects.create_user(
            username='single-adjust-other-staff', email='single-adjust-other-staff@example.com', password='x', user_type='staff',
        )

    def test_selecting_a_real_player_by_pk_applies_the_adjustment(self):
        response = self.client.post('/admin/points/pointsadjustment/', data={
            'user': str(self.player.pk),
            'points_delta': '500',
            'note': 'autocomplete test',
        })
        self.assertEqual(response.status_code, 200)
        balance = PointsBalance.objects.get(user=self.player)
        self.assertEqual(balance.balance, Decimal('500'))

    def test_selecting_a_staff_account_is_rejected(self):
        response = self.client.post('/admin/points/pointsadjustment/', data={
            'user': str(self.other_staff.pk),
            'points_delta': '500',
            'note': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PointsBalance.objects.filter(user=self.other_staff).exists())

    def test_the_autocomplete_endpoint_finds_the_player_by_partial_username(self):
        response = self.client.get(
            '/admin/autocomplete/',
            {'app_label': 'points', 'model_name': 'pointsbalance', 'field_name': 'user', 'term': 'single-adjust-play'},
        )
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertTrue(any(r['id'] == str(self.player.pk) for r in results))
