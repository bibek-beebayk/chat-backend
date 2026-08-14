from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from rest_framework.test import APIClient

from games.models import Game
from points.models import PointsBalance, PointsLedgerEntry
from points.services import InsufficientPoints
from .constants import GAME_VERSION, MAX_WAGER, MIN_WAGER, PAYLINES, PAYTABLE, REEL_STRIPS
from .models import SlotRound
from .services import SlotGameUnavailable, derive_grid, evaluate_paylines, play_round, spin_reel_stops


class SlotMathTests(TestCase):
    """
    Deterministic math tests, independent of RNG - the payline evaluator and
    grid derivation are pure functions of known reel-stop combinations.
    """

    def test_derive_grid_uses_adjacent_strip_positions(self):
        stops = [5, 10, 15]
        grid = derive_grid(stops)
        for reel_index, stop in enumerate(stops):
            strip = REEL_STRIPS[reel_index]
            n = len(strip)
            self.assertEqual(grid[reel_index][0], strip[(stop - 1) % n])
            self.assertEqual(grid[reel_index][1], strip[stop % n])
            self.assertEqual(grid[reel_index][2], strip[(stop + 1) % n])

    def test_derive_grid_wraps_at_strip_boundary(self):
        # stop=0 must wrap to the strip's last element for the "top" row.
        grid = derive_grid([0, 0, 0])
        for reel_index in range(3):
            strip = REEL_STRIPS[reel_index]
            self.assertEqual(grid[reel_index][0], strip[-1])
            self.assertEqual(grid[reel_index][1], strip[0])
            self.assertEqual(grid[reel_index][2], strip[1])

    def test_all_paylines_win_on_uniform_grid(self):
        grid = [['seven', 'seven', 'seven'], ['seven', 'seven', 'seven'], ['seven', 'seven', 'seven']]
        winning_lines, total_multiplier = evaluate_paylines(grid)
        self.assertEqual(len(winning_lines), len(PAYLINES))
        self.assertEqual(total_multiplier, PAYTABLE['seven'] * len(PAYLINES))
        for entry in winning_lines:
            self.assertEqual(entry['symbol'], 'seven')
            self.assertEqual(Decimal(entry['multiplier']), PAYTABLE['seven'])

    def test_no_line_wins_on_a_fully_mismatched_grid(self):
        grid = [['coin', 'gem', 'cards'], ['bell', 'crown', 'seven'], ['gem', 'coin', 'bell']]
        winning_lines, total_multiplier = evaluate_paylines(grid)
        self.assertEqual(winning_lines, [])
        self.assertEqual(total_multiplier, Decimal('0'))

    def test_only_middle_line_wins_when_only_middle_row_matches(self):
        # Line 0 = [1,1,1] (middle row). Everything else deliberately mismatched.
        grid = [
            ['coin', 'gem', 'cards'],
            ['bell', 'gem', 'seven'],
            ['gem', 'gem', 'crown'],
        ]
        winning_lines, total_multiplier = evaluate_paylines(grid)
        self.assertEqual(len(winning_lines), 1)
        self.assertEqual(winning_lines[0]['line_index'], 0)
        self.assertEqual(winning_lines[0]['symbol'], 'gem')
        self.assertEqual(total_multiplier, PAYTABLE['gem'])

    def test_v_line_evaluated_correctly_in_isolation(self):
        # Line 3 (V) = [0,1,0]: reel0 top, reel1 middle, reel2 top, all 'crown'.
        # Every other row/line deliberately mismatched so only line 3 wins.
        grid = [
            ['crown', 'x', 'gem'],
            ['y', 'crown', 'z'],
            ['crown', 'w', 'bell'],
        ]
        winning_lines, total_multiplier = evaluate_paylines(grid)
        self.assertEqual(len(winning_lines), 1)
        self.assertEqual(winning_lines[0]['line_index'], 3)
        self.assertEqual(winning_lines[0]['symbol'], 'crown')
        self.assertEqual(total_multiplier, PAYTABLE['crown'])

    def test_inverted_v_line_evaluated_correctly_in_isolation(self):
        # Line 4 (inverted V) = [2,1,2]: reel0 bottom, reel1 middle, reel2 bottom, all 'bell'.
        # Every other row/line deliberately mismatched so only line 4 wins.
        grid = [
            ['x', 'y', 'bell'],
            ['z', 'bell', 'w'],
            ['gem', 'coin', 'bell'],
        ]
        winning_lines, total_multiplier = evaluate_paylines(grid)
        self.assertEqual(len(winning_lines), 1)
        self.assertEqual(winning_lines[0]['line_index'], 4)
        self.assertEqual(winning_lines[0]['symbol'], 'bell')
        self.assertEqual(total_multiplier, PAYTABLE['bell'])

    def test_multiple_winning_lines_sum_multiplier_correctly(self):
        # Uniform top AND bottom rows (lines 1 and 2), different symbols, middle row mismatched.
        grid = [
            ['coin', 'x', 'gem'],
            ['coin', 'y', 'gem'],
            ['coin', 'z', 'gem'],
        ]
        winning_lines, total_multiplier = evaluate_paylines(grid)
        self.assertEqual(len(winning_lines), 2)
        symbols = {entry['symbol'] for entry in winning_lines}
        self.assertEqual(symbols, {'coin', 'gem'})
        self.assertEqual(total_multiplier, PAYTABLE['coin'] + PAYTABLE['gem'])

    def test_spin_reel_stops_within_strip_bounds(self):
        for _ in range(500):
            stops = spin_reel_stops()
            self.assertEqual(len(stops), 3)
            for reel_index, stop in enumerate(stops):
                self.assertGreaterEqual(stop, 0)
                self.assertLess(stop, len(REEL_STRIPS[reel_index]))


class SlotServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='slots-player',
            email='slots-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        Game.objects.update_or_create(slug='slots', defaults={'name': 'Rollin 3x3', 'is_active': True})
        PointsBalance.objects.create(user=self.user, balance=1000)

    def test_forced_stops_produce_expected_grid_and_payout(self):
        with mock.patch('slots.services.spin_reel_stops', return_value=[0, 0, 0]):
            round_obj, created = play_round(self.user, wager_amount=100)

        self.assertTrue(created)
        expected_grid = derive_grid([0, 0, 0])
        self.assertEqual(round_obj.grid_snapshot, expected_grid)
        winning_lines, total_multiplier = evaluate_paylines(expected_grid)
        self.assertEqual(round_obj.total_multiplier, total_multiplier)
        self.assertEqual(round_obj.payout_amount, (Decimal(100) * total_multiplier).quantize(Decimal('0.01')))

    def test_game_version_recorded_on_round(self):
        with mock.patch('slots.services.spin_reel_stops', return_value=[0, 0, 0]):
            round_obj, _ = play_round(self.user, wager_amount=100)
        self.assertEqual(round_obj.game_version, GAME_VERSION)

    def test_ledger_entry_created_and_linked(self):
        with mock.patch('slots.services.spin_reel_stops', return_value=[0, 0, 0]):
            round_obj, _ = play_round(self.user, wager_amount=100)

        self.assertIsNotNone(round_obj.ledger_entry)
        entry = round_obj.ledger_entry
        self.assertEqual(entry.entry_type, PointsLedgerEntry.ENTRY_GAME_ROUND)
        self.assertEqual(entry.delta, round_obj.payout_amount - round_obj.wager_amount)
        self.assertEqual(entry.balance_after, round_obj.balance_after)
        self.assertEqual(entry.metadata['game_version'], GAME_VERSION)
        self.assertEqual(entry.metadata['reel_stops'], [0, 0, 0])

    def test_balance_before_and_after_are_consistent(self):
        with mock.patch('slots.services.spin_reel_stops', return_value=[0, 0, 0]):
            round_obj, _ = play_round(self.user, wager_amount=100)
        self.assertEqual(
            round_obj.balance_after,
            round_obj.balance_before + round_obj.payout_amount - round_obj.wager_amount,
        )

    def test_insufficient_balance_raises_and_creates_no_round(self):
        PointsBalance.objects.filter(user=self.user).update(balance=5)
        with self.assertRaises(InsufficientPoints):
            play_round(self.user, wager_amount=100)
        self.assertEqual(SlotRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 5)

    def test_inactive_game_blocks_play(self):
        Game.objects.filter(slug='slots').update(is_active=False)
        with self.assertRaises(SlotGameUnavailable):
            play_round(self.user, wager_amount=100)
        self.assertEqual(SlotRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 1000)

    def test_balance_never_goes_negative_across_many_rounds(self):
        for _ in range(200):
            balance = PointsBalance.objects.get(user=self.user).balance
            if balance < MIN_WAGER:
                break
            play_round(self.user, wager_amount=MIN_WAGER)
        self.assertGreaterEqual(PointsBalance.objects.get(user=self.user).balance, 0)

    def test_idempotent_replay_returns_same_round_without_double_charge(self):
        with mock.patch('slots.services.spin_reel_stops', return_value=[0, 0, 0]):
            first_round, first_created = play_round(self.user, wager_amount=100, client_request_id='req-1')
        balance_after_first = PointsBalance.objects.get(user=self.user).balance

        with mock.patch('slots.services.spin_reel_stops', return_value=[5, 5, 5]):
            second_round, second_created = play_round(self.user, wager_amount=100, client_request_id='req-1')

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_round.id, second_round.id)
        self.assertEqual(SlotRound.objects.filter(user=self.user).count(), 1)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, balance_after_first)

    def test_blank_client_request_id_never_collides(self):
        with mock.patch('slots.services.spin_reel_stops', return_value=[0, 0, 0]):
            round_a, created_a = play_round(self.user, wager_amount=10, client_request_id='')
            round_b, created_b = play_round(self.user, wager_amount=10, client_request_id='')
        self.assertTrue(created_a)
        self.assertTrue(created_b)
        self.assertNotEqual(round_a.id, round_b.id)


class SlotConcurrencySafetyTests(TestCase):
    """
    Real multi-threaded concurrency testing needs TransactionTestCase (so
    separate DB connections can see each other's committed writes), but
    TransactionTestCase's teardown truncates the *entire* database
    (CASCADE follows every FK to the User table, i.e. effectively every
    app) - that repeatedly corrupted other apps' migration-seeded fixture
    data when the full suite ran together, even when scoped with
    available_apps/serialized_rollback. Plinko's own test suite doesn't
    attempt real thread-based concurrency testing either for the same
    settle_wager() row-lock, so this proves the safety property the same
    way: confirming play_round's balance read genuinely goes through
    settle_wager's SELECT ... FOR UPDATE (the mechanism that makes
    concurrent overspend impossible), plus a sequential stress run
    confirming the balance invariant (never negative) holds across many
    rounds.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='slots-concurrency-player',
            email='slots-concurrency-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        Game.objects.update_or_create(slug='slots', defaults={'name': 'Rollin 3x3', 'is_active': True})
        PointsBalance.objects.create(user=self.user, balance=100)

    def test_play_round_locks_the_balance_row_for_update(self):
        with CaptureQueriesContext(connection) as ctx:
            with mock.patch('slots.services.spin_reel_stops', return_value=[8, 6, 26]):
                play_round(self.user, wager_amount=50)

        locking_queries = [
            q for q in ctx.captured_queries
            if 'points_pointsbalance' in q['sql'].lower() and 'for update' in q['sql'].lower()
        ]
        self.assertTrue(locking_queries, 'Expected a SELECT ... FOR UPDATE against the balance row.')

    def test_sequential_spins_never_drive_balance_negative(self):
        for _ in range(50):
            balance = PointsBalance.objects.get(user=self.user).balance
            if balance < MIN_WAGER:
                break
            play_round(self.user, wager_amount=MIN_WAGER)
        self.assertGreaterEqual(PointsBalance.objects.get(user=self.user).balance, 0)


class SlotViewTests(TestCase):
    def setUp(self):
        self.player = get_user_model().objects.create_user(
            username='slots-view-player',
            email='slots-view-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.staff = get_user_model().objects.create_user(
            username='slots-view-staff',
            email='slots-view-staff@example.com',
            password='test-pass-123',
            user_type='staff',
        )
        Game.objects.update_or_create(slug='slots', defaults={'name': 'Rollin 3x3', 'is_active': True})
        PointsBalance.objects.create(user=self.player, balance=1000)
        self.client = APIClient()

    def test_requires_authentication(self):
        response = self.client.post(reverse('slots-play'), {'wager': 50})
        self.assertEqual(response.status_code, 401)

    def test_only_players_can_play(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(reverse('slots-play'), {'wager': 50})
        self.assertEqual(response.status_code, 403)

    def test_wager_outside_fixed_options_is_rejected(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('slots-play'), {'wager': 7})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SlotRound.objects.count(), 0)

    def test_zero_and_negative_wager_rejected(self):
        self.client.force_authenticate(user=self.player)
        for bad_wager in (0, -10):
            response = self.client.post(reverse('slots-play'), {'wager': bad_wager})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(SlotRound.objects.count(), 0)

    def test_wager_exceeding_balance_is_rejected(self):
        self.client.force_authenticate(user=self.player)
        PointsBalance.objects.filter(user=self.player).update(balance=0)  # below the smallest wager option (1)
        response = self.client.post(reverse('slots-play'), {'wager': MIN_WAGER})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SlotRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.player).balance, 0)

    def test_deactivated_game_blocks_play_via_api(self):
        Game.objects.filter(slug='slots').update(is_active=False)
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('slots-play'), {'wager': 10})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SlotRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.player).balance, 1000)

    def test_successful_play_returns_authoritative_result_and_updates_balance(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('slots-play'), {'wager': 10})
        self.assertEqual(response.status_code, 201)
        data = response.data
        for key in ('round_id', 'game_version', 'wager', 'reel_stops', 'grid', 'winning_lines', 'total_multiplier', 'payout', 'net', 'balance', 'created_at'):
            self.assertIn(key, data)
        self.assertEqual(data['game_version'], GAME_VERSION)
        self.assertEqual(data['wager'], 10)
        self.assertEqual(len(data['reel_stops']), 3)
        self.assertEqual(len(data['grid']), 3)
        self.assertEqual(PointsBalance.objects.get(user=self.player).balance, Decimal(str(data['balance'])))

    def test_client_cannot_override_payout_or_grid(self):
        # Server ignores any client-supplied result fields entirely - the
        # request serializer only accepts `wager` and `client_request_id`.
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('slots-play'), {
            'wager': 10,
            'payout': 999999,
            'total_multiplier': 999,
            'grid': [['seven', 'seven', 'seven']] * 3,
            'winning_lines': [{'line_index': 0, 'symbol': 'seven', 'multiplier': '75'}],
            'balance': 999999,
        })
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(Decimal(str(response.data['payout'])), Decimal('999999'))
        self.assertNotEqual(Decimal(str(response.data['balance'])), Decimal('999999'))

    def test_config_endpoint_returns_full_configuration(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.get(reverse('slots-config'))
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertTrue(data['enabled'])
        self.assertEqual(data['game_version'], GAME_VERSION)
        self.assertEqual(data['min_wager'], MIN_WAGER)
        self.assertEqual(data['max_wager'], MAX_WAGER)
        self.assertEqual(len(data['symbols']), 6)
        self.assertEqual(len(data['paytable']), 6)
        self.assertEqual(data['paylines'], PAYLINES)
        self.assertEqual(data['reel_strips'], REEL_STRIPS)

    def test_idempotent_retry_via_api_does_not_double_charge(self):
        self.client.force_authenticate(user=self.player)
        first = self.client.post(reverse('slots-play'), {'wager': 10, 'client_request_id': 'dup-key-1'})
        self.assertEqual(first.status_code, 201)
        balance_after_first = PointsBalance.objects.get(user=self.player).balance

        second = self.client.post(reverse('slots-play'), {'wager': 10, 'client_request_id': 'dup-key-1'})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['round_id'], first.data['round_id'])
        self.assertEqual(SlotRound.objects.filter(user=self.player).count(), 1)
        self.assertEqual(PointsBalance.objects.get(user=self.player).balance, balance_after_first)

    def test_history_returns_own_rounds_only_most_recent_first(self):
        self.client.force_authenticate(user=self.player)
        self.client.post(reverse('slots-play'), {'wager': 10})
        self.client.post(reverse('slots-play'), {'wager': 20})

        other_player = get_user_model().objects.create_user(
            username='slots-other-player',
            email='slots-other-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        PointsBalance.objects.create(user=other_player, balance=1000)
        other_client = APIClient()
        other_client.force_authenticate(user=other_player)
        other_client.post(reverse('slots-play'), {'wager': 5})

        response = self.client.get(reverse('slots-history'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]['wager'], 20)  # most recent first
        self.assertEqual(response.data[1]['wager'], 10)
