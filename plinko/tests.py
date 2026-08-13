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
        Regression guard: only the first BIAS_ROWS bounces are biased toward the
        drop side (the rest stay fair), which is what keeps this safe - biasing
        every row instead lets a player push several tables well past 100% RTP
        with only a few points of shift (verified by hand during planning).
        This recomputes the exact worst-case EV at maximum bias across every
        table and asserts it stays comfortably under 1.0.
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

        self.assertLess(worst, 0.99, f'Worst-case biased EV too high: {worst} ({worst_id})')


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
        self.assertEqual(round_obj.multiplier, Decimal('5.49'))
        self.assertEqual(round_obj.payout_amount, 549)  # round_half_up(100 * 5.49)
        self.assertEqual(round_obj.path, [1] * 8)

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
        response = self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 100000})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlinkoRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.player).balance, 1000)

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
        self.assertEqual(response.data['rows_options'], [8, 12, 16])
        self.assertEqual(response.data['multipliers'][8]['low'][0], 5.49)

    def test_deactivated_game_blocks_play_via_api(self):
        Game.objects.filter(slug='plinko').update(is_active=False)
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 10})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PlinkoRound.objects.count(), 0)
        self.assertEqual(PointsBalance.objects.get(user=self.player).balance, 1000)

    def test_successful_play_returns_round_and_updates_balance(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(reverse('plinko-play'), {'rows': 8, 'risk_level': 'low', 'wager_amount': 100})
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
