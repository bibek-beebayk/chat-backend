from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from games.models import Game
from points.models import PointsBalance
from points.services import InsufficientPoints
from .constants import HOUSE_EDGE, INSTANT_CRASH_PROBABILITY
from .models import RocketRound
from .services import (
    ActiveRoundExists,
    NoActiveRound,
    RoundAlreadyResolved,
    TooEarlyToCashOut,
    cash_out,
    generate_crash_point,
    get_current_round,
    multiplier_at_elapsed,
    place_bet,
)


class RocketMathTests(TestCase):
    """Pure-function tests, independent of the DB/RNG seeding of any round."""

    def test_multiplier_is_one_before_launch(self):
        self.assertEqual(multiplier_at_elapsed(Decimal('0')), Decimal('1.00'))
        self.assertEqual(multiplier_at_elapsed(Decimal('-2')), Decimal('1.00'))

    def test_multiplier_strictly_increases_with_elapsed_time(self):
        samples = [Decimal(v) for v in ['0.5', '1', '2', '5', '8', '12', '18']]
        values = [multiplier_at_elapsed(s) for s in samples]
        for a, b in zip(values, values[1:]):
            self.assertLess(a, b)

    def test_crash_point_never_below_one(self):
        for _ in range(2000):
            self.assertGreaterEqual(generate_crash_point(), Decimal('1.00'))

    def test_crash_point_respects_max_cap(self):
        from .constants import MAX_CRASH_MULTIPLIER
        for _ in range(2000):
            self.assertLessEqual(generate_crash_point(), MAX_CRASH_MULTIPLIER)

    def test_crash_distribution_produces_both_very_low_and_very_high_outcomes(self):
        # Not a precise distribution-shape assertion (that's the RTP test
        # below) - just confirms the formula genuinely spans both ends
        # rather than being a narrow/degenerate distribution.
        samples = [generate_crash_point() for _ in range(5000)]
        self.assertTrue(any(s <= Decimal('1.50') for s in samples), 'Expected some low-multiplier crashes.')
        self.assertTrue(any(s >= Decimal('5.00') for s in samples), 'Expected some high-multiplier crashes.')

    def test_rtp_is_approximately_uniform_across_fixed_cashout_strategies(self):
        """
        By construction (see constants.py's derivation), cashing out at any
        FIXED multiplier M should have expected return ~= (1 - HOUSE_EDGE)
        per unit staked *for the smooth-tail formula alone*. The flat
        INSTANT_CRASH_PROBABILITY injection sits on top of that and forces
        an extra slice of rounds to crash at exactly 1.00x regardless of
        what the formula would have produced, which scales the true
        achievable RTP down by (1 - INSTANT_CRASH_PROBABILITY) for any
        M > 1. Empirically verify that combined figure over a large
        sample, with a generous tolerance for RNG/sample-size noise.
        """
        expected_rtp = float((Decimal('1') - INSTANT_CRASH_PROBABILITY) * (Decimal('1') - HOUSE_EDGE))
        samples = [generate_crash_point() for _ in range(200000)]
        for cashout_at in [Decimal('1.5'), Decimal('2.0'), Decimal('5.0')]:
            wins = sum(1 for s in samples if s >= cashout_at)
            rtp = (wins / len(samples)) * float(cashout_at)
            self.assertAlmostEqual(rtp, expected_rtp, delta=0.03, msg=f'RTP for cashout={cashout_at} was {rtp}')


class RocketServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='rocket-player',
            email='rocket-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        Game.objects.update_or_create(slug='rocket', defaults={'name': 'Rollin Rocket', 'is_active': True})
        PointsBalance.objects.create(user=self.user, balance=1000)

    def _force_launch(self, round_obj, seconds_ago=1):
        """Backdates started_at so the round is already past its countdown."""
        round_obj.started_at = timezone.now() - timezone.timedelta(seconds=seconds_ago)
        round_obj.save(update_fields=['started_at'])
        return round_obj

    def test_place_bet_debits_balance_immediately(self):
        round_obj, created = place_bet(self.user, wager_amount=Decimal('100'))
        self.assertTrue(created)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, Decimal('900'))
        self.assertEqual(round_obj.status, RocketRound.STATUS_ACTIVE)

    def test_insufficient_balance_raises_and_creates_no_round(self):
        PointsBalance.objects.filter(user=self.user).update(balance=5)
        with self.assertRaises(InsufficientPoints):
            place_bet(self.user, wager_amount=Decimal('100'))
        self.assertEqual(RocketRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 5)

    def test_second_bet_while_one_is_active_is_rejected_and_not_double_charged(self):
        place_bet(self.user, wager_amount=Decimal('100'))
        with self.assertRaises(ActiveRoundExists):
            place_bet(self.user, wager_amount=Decimal('50'))
        # The rejected attempt's debit must have rolled back.
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, Decimal('900'))
        self.assertEqual(RocketRound.objects.count(), 1)

    def test_client_request_id_replays_existing_round_without_double_charge(self):
        first, created_a = place_bet(self.user, wager_amount=Decimal('100'), client_request_id='req-1')
        second, created_b = place_bet(self.user, wager_amount=Decimal('100'), client_request_id='req-1')
        self.assertTrue(created_a)
        self.assertFalse(created_b)
        self.assertEqual(first.id, second.id)
        self.assertEqual(RocketRound.objects.count(), 1)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, Decimal('900'))

    def test_cashout_before_crash_pays_out_and_credits_balance(self):
        with mock.patch('rocket.services.generate_crash_point', return_value=Decimal('5.00')):
            round_obj, _ = place_bet(self.user, wager_amount=Decimal('100'))
        self._force_launch(round_obj, seconds_ago=1)  # ~1.16x at t=1s per the growth curve

        result = cash_out(self.user)
        self.assertEqual(result.status, RocketRound.STATUS_CASHED_OUT)
        self.assertGreater(result.cashout_multiplier, Decimal('1.00'))
        self.assertLess(result.cashout_multiplier, Decimal('5.00'))
        expected_payout = (Decimal('100') * result.cashout_multiplier).quantize(Decimal('0.01'))
        self.assertEqual(result.payout_amount, expected_payout)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, Decimal('900') + expected_payout)

    def test_cashout_after_crash_point_reached_settles_as_crashed_not_paid(self):
        with mock.patch('rocket.services.generate_crash_point', return_value=Decimal('1.01')):
            round_obj, _ = place_bet(self.user, wager_amount=Decimal('100'))
        self._force_launch(round_obj, seconds_ago=20)  # way past any low crash point

        with self.assertRaises(RoundAlreadyResolved) as ctx:
            cash_out(self.user)
        self.assertEqual(ctx.exception.round_obj.status, RocketRound.STATUS_CRASHED)
        # No credit - balance reflects only the original debit.
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, Decimal('900'))

    def test_cashout_before_launch_is_rejected(self):
        place_bet(self.user, wager_amount=Decimal('100'))
        with self.assertRaises(TooEarlyToCashOut):
            cash_out(self.user)

    def test_cashout_with_no_active_round_raises(self):
        with self.assertRaises(NoActiveRound):
            cash_out(self.user)

    def test_duplicate_cashout_is_idempotent_not_double_paid(self):
        with mock.patch('rocket.services.generate_crash_point', return_value=Decimal('50.00')):
            round_obj, _ = place_bet(self.user, wager_amount=Decimal('100'))
        self._force_launch(round_obj, seconds_ago=1)

        first = cash_out(self.user)
        with self.assertRaises(RoundAlreadyResolved) as ctx:
            cash_out(self.user)
        self.assertEqual(ctx.exception.round_obj.id, first.id)
        self.assertEqual(ctx.exception.round_obj.cashout_multiplier, first.cashout_multiplier)
        balance_after_first = first.balance_after
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, balance_after_first)

    def test_auto_cashout_triggers_at_configured_multiplier_not_discovery_time_value(self):
        with mock.patch('rocket.services.generate_crash_point', return_value=Decimal('50.00')):
            round_obj, _ = place_bet(self.user, wager_amount=Decimal('100'), auto_cashout_multiplier=Decimal('2.00'))
        self._force_launch(round_obj, seconds_ago=20)  # multiplier is now far past 2x by the time this is checked

        resolved = get_current_round(self.user)
        self.assertEqual(resolved.status, RocketRound.STATUS_CASHED_OUT)
        self.assertEqual(resolved.cashout_multiplier, Decimal('2.00'))
        self.assertEqual(resolved.payout_amount, Decimal('200.00'))

    def test_auto_cashout_above_crash_point_still_crashes(self):
        with mock.patch('rocket.services.generate_crash_point', return_value=Decimal('1.50')):
            round_obj, _ = place_bet(self.user, wager_amount=Decimal('100'), auto_cashout_multiplier=Decimal('10.00'))
        self._force_launch(round_obj, seconds_ago=20)

        resolved = get_current_round(self.user)
        self.assertEqual(resolved.status, RocketRound.STATUS_CRASHED)

    def test_get_current_round_returns_none_when_nothing_active(self):
        self.assertIsNone(get_current_round(self.user))

    def test_reconnect_restores_active_round_without_creating_another(self):
        round_obj, _ = place_bet(self.user, wager_amount=Decimal('100'))
        restored = get_current_round(self.user)
        self.assertEqual(restored.id, round_obj.id)
        self.assertEqual(RocketRound.objects.filter(user=self.user).count(), 1)


class RocketConcurrencySafetyTests(TestCase):
    """
    Mirrors slots/tests.py::SlotConcurrencySafetyTests - proves the row-lock
    mechanism is actually engaged (via captured SQL) rather than attempting
    true multi-threaded concurrency (which corrupts shared fixture data when
    run as part of the full suite - see that file's own docstring for why).
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='rocket-concurrency-player',
            email='rocket-concurrency-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        Game.objects.update_or_create(slug='rocket', defaults={'name': 'Rollin Rocket', 'is_active': True})
        PointsBalance.objects.create(user=self.user, balance=1000)

    def test_cash_out_locks_the_round_row_for_update(self):
        with mock.patch('rocket.services.generate_crash_point', return_value=Decimal('50.00')):
            round_obj, _ = place_bet(self.user, wager_amount=Decimal('100'))
        round_obj.started_at = timezone.now() - timezone.timedelta(seconds=1)
        round_obj.save(update_fields=['started_at'])

        with CaptureQueriesContext(connection) as ctx:
            cash_out(self.user)

        locking_queries = [
            q for q in ctx.captured_queries
            if 'rocket_rocketround' in q['sql'].lower() and 'for update' in q['sql'].lower()
        ]
        self.assertTrue(locking_queries, 'Expected a SELECT ... FOR UPDATE against the round row.')

    def test_place_bet_locks_the_balance_row_for_update(self):
        with CaptureQueriesContext(connection) as ctx:
            place_bet(self.user, wager_amount=Decimal('50'))

        locking_queries = [
            q for q in ctx.captured_queries
            if 'points_pointsbalance' in q['sql'].lower() and 'for update' in q['sql'].lower()
        ]
        self.assertTrue(locking_queries, 'Expected a SELECT ... FOR UPDATE against the balance row.')


class RocketViewTests(TestCase):
    def setUp(self):
        self.player = get_user_model().objects.create_user(
            username='rocket-view-player',
            email='rocket-view-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.staff = get_user_model().objects.create_user(
            username='rocket-view-staff',
            email='rocket-view-staff@example.com',
            password='test-pass-123',
            user_type='staff',
        )
        Game.objects.update_or_create(slug='rocket', defaults={'name': 'Rollin Rocket', 'is_active': True})
        PointsBalance.objects.create(user=self.player, balance=1000)
        self.client = APIClient()

    def test_requires_authentication(self):
        response = self.client.post(reverse('rocket-play'), {'wager_amount': '50'})
        self.assertEqual(response.status_code, 401)

    def test_only_players_can_play(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(reverse('rocket-play'), {'wager_amount': '50'})
        self.assertEqual(response.status_code, 403)

    def test_config_endpoint_returns_configuration(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.get(reverse('rocket-config'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['enabled'])
        self.assertIn('wager_quick_amounts', response.data)
        self.assertIn('auto_cashout_quick_options', response.data)

    def test_wager_below_minimum_rejected(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('rocket-play'), {'wager_amount': '0'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(RocketRound.objects.count(), 0)

    def test_wager_exceeding_balance_is_rejected(self):
        self.client.force_authenticate(user=self.player)
        PointsBalance.objects.filter(user=self.player).update(balance=5)
        response = self.client.post(reverse('rocket-play'), {'wager_amount': '50'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(RocketRound.objects.count(), 0)

    def test_play_returns_countdown_phase_and_hides_crash_point(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('rocket-play'), {'wager_amount': '50'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['phase'], 'countdown')
        self.assertEqual(response.data['multiplier'], '1.00')
        self.assertNotIn('crash_point', response.data)

    def test_second_play_while_active_returns_conflict(self):
        self.client.force_authenticate(user=self.player)
        self.client.post(reverse('rocket-play'), {'wager_amount': '50'})
        response = self.client.post(reverse('rocket-play'), {'wager_amount': '50'})
        self.assertEqual(response.status_code, 409)
        self.assertIn('active_round', response.data)

    def test_cashout_before_launch_returns_400(self):
        self.client.force_authenticate(user=self.player)
        self.client.post(reverse('rocket-play'), {'wager_amount': '50'})
        response = self.client.post(reverse('rocket-cashout'))
        self.assertEqual(response.status_code, 400)

    def test_full_play_launch_cashout_flow_via_api(self):
        self.client.force_authenticate(user=self.player)
        with mock.patch('rocket.services.generate_crash_point', return_value=Decimal('5.00')):
            play_response = self.client.post(reverse('rocket-play'), {'wager_amount': '100'})
        self.assertEqual(play_response.status_code, 201)
        round_id = play_response.data['round_id']

        RocketRound.objects.filter(id=round_id).update(
            started_at=timezone.now() - timezone.timedelta(seconds=1),
        )

        current_response = self.client.get(reverse('rocket-current'))
        self.assertEqual(current_response.status_code, 200)
        self.assertEqual(current_response.data['phase'], 'running')

        cashout_response = self.client.post(reverse('rocket-cashout'))
        self.assertEqual(cashout_response.status_code, 200)
        self.assertEqual(cashout_response.data['status'], 'cashed_out')
        self.assertIn('cashout_multiplier', cashout_response.data)

        history_response = self.client.get(reverse('rocket-history'))
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(len(history_response.data), 1)
        self.assertEqual(history_response.data[0]['round_id'], round_id)

    def test_current_round_returns_null_when_nothing_active(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.get(reverse('rocket-current'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data)
