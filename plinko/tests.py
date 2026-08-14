import math
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from games.models import Game
from points.models import PointsBalance, PointsLedgerEntry
from .constants import BIAS_ROWS, MAX_BIAS, MULTIPLIER_TABLES
from .free_drop_constants import (
    FREE_DROP_BIAS_ROWS,
    FREE_DROP_MAX_BIAS,
    FREE_DROP_MULTIPLIER_TABLES,
)
from .free_drop_services import generate_free_drop_path, play_free_drop_round
from .models import PlinkoRound
from .services import GameUnavailable, generate_path, play_round


class PlinkoMultiplierTableTests(TestCase):
    def test_multiplier_table_expected_values(self):
        for rows, risk_tables in MULTIPLIER_TABLES.items():
            for risk_level, table in risk_tables.items():
                self.assertEqual(len(table), rows + 1)
                self.assertEqual(table, table[::-1], f'{rows}/{risk_level} is not symmetric')
                total = sum(Decimal(str(m)) * math.comb(rows, k) for k, m in enumerate(table))
                ev = total / Decimal(2 ** rows)
                self.assertGreater(ev, Decimal('0.85'), f'{rows}/{risk_level} EV too low: {ev}')
                self.assertLess(ev, Decimal('0.99'), f'{rows}/{risk_level} EV too high: {ev}')

    def test_bias_worst_case_ev_stays_safe(self):
        """
        Regression guard for generate_path()'s bias math in isolation. This is
        no longer a live threat model - play_round() always calls
        generate_path(rows, 0.0) regardless of what drop_offset a client
        sends (see services.py), so this scenario can't actually happen
        through the API today. It's kept as a defense-in-depth property: if
        play_round() ever passes a real client offset through again, the
        underlying math must still guarantee the house can't net negative
        even at maximum drag. Threshold is 1.0 (break-even), not the tighter
        margin used back when this was a reachable path.
        """
        biased_p = 0.5 + MAX_BIAS

        def ev_partial_bias(rows, table):
            n_biased = min(BIAS_ROWS, rows)
            n_fair = rows - n_biased
            dist_biased = [
                math.comb(n_biased, k) * (biased_p ** k) * ((1 - biased_p) ** (n_biased - k))
                for k in range(n_biased + 1)
            ]
            dist_fair = [math.comb(n_fair, k) * (0.5 ** n_fair) for k in range(n_fair + 1)]
            total = 0.0
            for kb, pb in enumerate(dist_biased):
                for kf, pf in enumerate(dist_fair):
                    total += pb * pf * table[kb + kf]
            return total

        worst = 0.0
        worst_id = None
        for rows, risk_tables in MULTIPLIER_TABLES.items():
            for risk_level, table in risk_tables.items():
                ev = ev_partial_bias(rows, table)
                if ev > worst:
                    worst = ev
                    worst_id = (rows, risk_level)

        self.assertLess(worst, 1.0, f'Worst-case biased EV too high: {worst} ({worst_id})')


class PlinkoServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='plinko-player',
            email='plinko-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        Game.objects.filter(slug='plinko').update(is_active=True)
        PointsBalance.objects.create(user=self.user, balance=1000)

    def test_forced_path_produces_expected_outcome(self):
        with mock.patch('plinko.services.generate_path', return_value=[1] * 8):
            round_obj = play_round(self.user, rows=8, risk_level='low', wager_amount=100)

        self.assertEqual(round_obj.slot_index, 8)
        self.assertEqual(round_obj.multiplier, Decimal('5.57'))
        self.assertEqual(round_obj.payout_amount, Decimal('557.00'))  # 100 * 5.57, exact to 2dp
        self.assertEqual(round_obj.path, [1] * 8)

    def test_payout_keeps_fractional_cents_instead_of_rounding_to_whole_points(self):
        # A wager whose product with the multiplier isn't a whole number is
        # the actual regression this covers - e.g. a 5-point wager at a
        # 1.1x multiplier settles at 5.50, not rounded to 5 or 6.
        with mock.patch('plinko.services.generate_path', return_value=[1, 1, 0, 0, 0, 0, 0, 0]):
            round_obj = play_round(self.user, rows=8, risk_level='low', wager_amount=5)

        self.assertEqual(round_obj.slot_index, 2)
        self.assertEqual(round_obj.multiplier, Decimal('1.1'))
        self.assertEqual(round_obj.payout_amount, Decimal('5.50'))

    def test_ledger_entry_created_with_expected_delta_and_metadata(self):
        with mock.patch('plinko.services.generate_path', return_value=[0] * 8):
            round_obj = play_round(self.user, rows=8, risk_level='low', wager_amount=100)

        self.assertEqual(
            PointsLedgerEntry.objects.filter(user=self.user, entry_type=PointsLedgerEntry.ENTRY_GAME_ROUND).count(),
            1,
        )
        entry = round_obj.ledger_entry
        self.assertIsNotNone(entry)
        self.assertEqual(entry.delta, round_obj.payout_amount - round_obj.wager_amount)
        self.assertEqual(entry.metadata['game'], 'plinko')
        self.assertEqual(entry.metadata['slot_index'], 0)

    def test_inactive_game_blocks_play(self):
        Game.objects.filter(slug='plinko').update(is_active=False)
        with self.assertRaises(GameUnavailable):
            play_round(self.user, rows=8, risk_level='low', wager_amount=100)

        self.assertEqual(PlinkoRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 1000)

    def test_balance_never_goes_negative_across_many_rounds(self):
        for _ in range(500):
            balance = PointsBalance.objects.get(user=self.user).balance
            if balance < 1:
                break
            wager = min(balance, 10)
            play_round(self.user, rows=8, risk_level='high', wager_amount=wager)
            self.assertGreaterEqual(PointsBalance.objects.get(user=self.user).balance, 0)

    def test_drop_offset_statistically_biases_outcome(self):
        # Real RNG, no mocking - sanity check the bias actually points the
        # right direction. Only the count of "right" bounces (sum(path)) is
        # affected, so we can call generate_path directly without spending
        # points on hundreds of rounds.
        rows = 8
        right_totals = sum(sum(generate_path(rows, drop_offset=1.0)) for _ in range(300))
        left_totals = sum(sum(generate_path(rows, drop_offset=-1.0)) for _ in range(300))
        self.assertGreater(right_totals, left_totals)

    def test_drop_offset_clamped_beyond_range(self):
        # generate_path clamps internally; play_round should not error on an
        # out-of-range value that already passed serializer validation elsewhere.
        with mock.patch('plinko.services._rng') as mock_rng:
            mock_rng.random.return_value = 0.0  # always "right"
            round_obj = play_round(self.user, rows=8, risk_level='low', wager_amount=10, drop_offset=5.0)
        self.assertEqual(round_obj.drop_offset, 1.0)

    def test_drop_offset_no_longer_influences_path_generation(self):
        # The actual fix this covers: play_round() must always call
        # generate_path(rows, 0.0) regardless of what drop_offset a client
        # sends - only the stored/echoed field should reflect the clamped
        # value now (see services.py for why: the drag-to-bias mechanic this
        # powered no longer exists in the frontend physics, so honoring a
        # nonzero offset here would just be a dormant EV exploit).
        with mock.patch('plinko.services.generate_path', wraps=generate_path) as spy:
            play_round(self.user, rows=8, risk_level='low', wager_amount=5, drop_offset=1.0)
        spy.assert_called_once_with(8, 0.0)


class PlinkoViewTests(TestCase):
    def setUp(self):
        self.player = get_user_model().objects.create_user(
            username='plinko-view-player',
            email='plinko-view-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.staff = get_user_model().objects.create_user(
            username='plinko-view-staff',
            email='plinko-view-staff@example.com',
            password='test-pass-123',
            user_type='staff',
        )
        Game.objects.filter(slug='plinko').update(is_active=True)
        PointsBalance.objects.create(user=self.player, balance=1000)
        self.client = APIClient()

    def test_wager_exceeding_balance_is_rejected(self):
        self.client.force_authenticate(user=self.player)
        PointsBalance.objects.filter(user=self.player).update(balance=3)  # below the smallest wager option (5)
        response = self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 5})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlinkoRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.player).balance, 3)

    def test_wager_outside_fixed_options_is_rejected(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 7})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlinkoRound.objects.count(), 0)

    def test_only_players_can_play(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 10})
        self.assertEqual(response.status_code, 403)

    def test_requires_authentication(self):
        response = self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 10})
        self.assertEqual(response.status_code, 401)

    def test_config_endpoint_returns_all_tables(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.get(reverse('plinko-config'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['rows_options'], [8])
        self.assertEqual(response.data['wager_options'], [5, 10])
        self.assertEqual(response.data['multipliers'][8]['low'][0], 5.57)

    def test_deactivated_game_blocks_play_via_api(self):
        Game.objects.filter(slug='plinko').update(is_active=False)
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 10})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlinkoRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.player).balance, 1000)

    def test_successful_play_returns_round_and_updates_balance(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 10})
        self.assertEqual(response.status_code, 201)
        self.assertIn('slot_index', response.data)
        self.assertEqual(PlinkoRound.objects.filter(user=self.player).count(), 1)

    def test_drop_offset_out_of_range_rejected(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(
            reverse('plinko-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_offset': 1.5},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlinkoRound.objects.count(), 0)

    def test_drop_offset_defaults_to_zero_when_omitted(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 10})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['drop_offset'], 0.0)


class FreeDropMultiplierTableTests(TestCase):
    def test_multiplier_table_expected_values(self):
        for rows, risk_tables in FREE_DROP_MULTIPLIER_TABLES.items():
            for risk_level, table in risk_tables.items():
                self.assertEqual(len(table), rows + 1)
                self.assertEqual(table, table[::-1], f'{rows}/{risk_level} is not symmetric')
                total = sum(Decimal(str(m)) * math.comb(rows, k) for k, m in enumerate(table))
                ev = total / Decimal(2 ** rows)
                self.assertGreater(ev, Decimal('0.85'), f'{rows}/{risk_level} EV too low: {ev}')
                self.assertLess(ev, Decimal('0.99'), f'{rows}/{risk_level} EV too high: {ev}')

    def test_bias_worst_case_ev_stays_safe_at_every_drop_position(self):
        """
        Unlike Classic's equivalent test, this bias IS live in play_free_drop_round
        - a player's drop_position directly sets biased_p for the first
        FREE_DROP_BIAS_ROWS bounces (see free_drop_services.py). EV is
        monotonic in |drop_position| under this model (bias only ever shifts
        weight toward the favored side of a symmetric table), so the worst
        case is always the most extreme position, +/-1.0. This must stay
        safely under 1.0 (house edge preserved) for every risk tier.
        """
        biased_p = 0.5 + FREE_DROP_MAX_BIAS

        def ev_partial_bias(rows, table):
            n_biased = min(FREE_DROP_BIAS_ROWS, rows)
            n_fair = rows - n_biased
            dist_biased = [
                math.comb(n_biased, k) * (biased_p ** k) * ((1 - biased_p) ** (n_biased - k))
                for k in range(n_biased + 1)
            ]
            dist_fair = [math.comb(n_fair, k) * (0.5 ** n_fair) for k in range(n_fair + 1)]
            total = 0.0
            for kb, pb in enumerate(dist_biased):
                for kf, pf in enumerate(dist_fair):
                    total += pb * pf * table[kb + kf]
            return total

        worst = 0.0
        worst_id = None
        for rows, risk_tables in FREE_DROP_MULTIPLIER_TABLES.items():
            for risk_level, table in risk_tables.items():
                ev = ev_partial_bias(rows, table)
                if ev > worst:
                    worst = ev
                    worst_id = (rows, risk_level)

        self.assertLess(worst, 0.99, f'Worst-case biased EV too high: {worst} ({worst_id})')


class FreeDropServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='free-drop-player',
            email='free-drop-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        Game.objects.filter(slug='plinko').update(is_active=True)
        PointsBalance.objects.create(user=self.user, balance=1000)

    def test_forced_path_produces_expected_outcome(self):
        with mock.patch('plinko.free_drop_services.generate_free_drop_path', return_value=[1] * 8):
            round_obj = play_free_drop_round(self.user, rows=8, risk_level='low', wager_amount=100, drop_position=0.5)

        self.assertEqual(round_obj.mode, PlinkoRound.MODE_FREE_DROP)
        self.assertEqual(round_obj.slot_index, 8)
        self.assertEqual(round_obj.multiplier, Decimal('5.49'))
        self.assertEqual(round_obj.payout_amount, Decimal('549.00'))
        self.assertEqual(round_obj.drop_position, 0.5)

    def test_drop_position_clamped_beyond_range(self):
        with mock.patch('plinko.free_drop_services._rng') as mock_rng:
            mock_rng.random.return_value = 1.0  # always "left"
            round_obj = play_free_drop_round(self.user, rows=8, risk_level='low', wager_amount=10, drop_position=5.0)
        self.assertEqual(round_obj.drop_position, 1.0)

    def test_drop_position_statistically_biases_outcome(self):
        rows = 8
        right_totals = sum(sum(generate_free_drop_path(rows, drop_position=1.0)) for _ in range(300))
        left_totals = sum(sum(generate_free_drop_path(rows, drop_position=-1.0)) for _ in range(300))
        self.assertGreater(right_totals, left_totals)

    def test_ledger_entry_records_mode_and_drop_position(self):
        with mock.patch('plinko.free_drop_services.generate_free_drop_path', return_value=[0] * 8):
            round_obj = play_free_drop_round(self.user, rows=8, risk_level='low', wager_amount=100, drop_position=-0.3)

        entry = round_obj.ledger_entry
        self.assertIsNotNone(entry)
        self.assertEqual(entry.metadata['game'], 'plinko')
        self.assertEqual(entry.metadata['mode'], 'free_drop')
        self.assertEqual(entry.metadata['drop_position'], '-0.3')

    def test_inactive_game_blocks_play(self):
        Game.objects.filter(slug='plinko').update(is_active=False)
        with self.assertRaises(GameUnavailable):
            play_free_drop_round(self.user, rows=8, risk_level='low', wager_amount=100, drop_position=0.0)

        self.assertEqual(PlinkoRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 1000)

    def test_balance_never_goes_negative_across_many_rounds(self):
        for _ in range(500):
            balance = PointsBalance.objects.get(user=self.user).balance
            if balance < 1:
                break
            wager = min(balance, 10)
            play_free_drop_round(self.user, rows=8, risk_level='high', wager_amount=wager, drop_position=1.0)
            self.assertGreaterEqual(PointsBalance.objects.get(user=self.user).balance, 0)

    def test_classic_round_does_not_gain_drop_position(self):
        # Cross-mode isolation guard: Classic rounds must keep drop_position
        # null - Free Drop's field should never leak a value onto Classic play.
        with mock.patch('plinko.services.generate_path', return_value=[1] * 8):
            classic_round = play_round(self.user, rows=8, risk_level='low', wager_amount=10)
        self.assertEqual(classic_round.mode, PlinkoRound.MODE_CLASSIC)
        self.assertIsNone(classic_round.drop_position)


class FreeDropViewTests(TestCase):
    def setUp(self):
        self.player = get_user_model().objects.create_user(
            username='free-drop-view-player',
            email='free-drop-view-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.staff = get_user_model().objects.create_user(
            username='free-drop-view-staff',
            email='free-drop-view-staff@example.com',
            password='test-pass-123',
            user_type='staff',
        )
        Game.objects.filter(slug='plinko').update(is_active=True)
        PointsBalance.objects.create(user=self.player, balance=1000)
        self.client = APIClient()

    def test_config_endpoint_returns_free_drop_tables(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.get(reverse('plinko-free-drop-config'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['rows_options'], [8])
        self.assertEqual(response.data['wager_options'], [5, 10])
        self.assertEqual(response.data['multipliers'][8]['low'][0], 5.49)

    def test_drop_position_is_required(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('plinko-free-drop-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 10})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlinkoRound.objects.count(), 0)

    def test_drop_position_out_of_range_rejected(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': 1.5},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlinkoRound.objects.count(), 0)

    def test_only_players_can_play(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': 0.0},
        )
        self.assertEqual(response.status_code, 403)

    def test_requires_authentication(self):
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': 0.0},
        )
        self.assertEqual(response.status_code, 401)

    def test_successful_play_returns_round_with_mode_and_drop_position(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': 0.4},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['mode'], 'free_drop')
        self.assertEqual(response.data['drop_position'], 0.4)
        self.assertEqual(PlinkoRound.objects.filter(user=self.player, mode='free_drop').count(), 1)

    def test_wager_exceeding_balance_is_rejected(self):
        self.client.force_authenticate(user=self.player)
        PointsBalance.objects.filter(user=self.player).update(balance=3)
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 5, 'drop_position': 0.0},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlinkoRound.objects.count(), 0)

    def test_deactivated_game_blocks_play_via_api(self):
        Game.objects.filter(slug='plinko').update(is_active=False)
        self.client.force_authenticate(user=self.player)
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': 0.0},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlinkoRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.player).balance, 1000)

    def test_history_endpoint_includes_both_modes(self):
        self.client.force_authenticate(user=self.player)
        self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 10})
        self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': 0.0},
        )
        response = self.client.get(reverse('plinko-history'))
        self.assertEqual(response.status_code, 200)
        modes = {row['mode'] for row in response.data}
        self.assertEqual(modes, {'classic', 'free_drop'})
