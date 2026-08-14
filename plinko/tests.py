import math
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from games.models import Game
from points.models import PointsBalance, PointsLedgerEntry
from xp.models import XPBalance, XPLedgerEntry
from .constants import BIAS_ROWS, MAX_BIAS, MULTIPLIER_TABLES
from .free_drop_constants import (
    DROP_BUCKETS,
    FREE_DROP_MULTIPLIER_TABLES,
    FREE_DROP_PHYSICS_TABLE,
    _validate_physics_table,
    bucket_index_for_drop_position,
    get_physics_table,
)
from .free_drop_services import pick_free_drop_outcome, play_free_drop_round
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
    def test_multiplier_table_shape(self):
        # Structural checks only - unlike Classic, Free Drop's outcome
        # distribution is NOT a fair-coin binomial walk (a player's chosen
        # position skews it directly), so a closed-form binomial EV formula
        # doesn't apply here. The real EV check against the actual
        # physics-derived distribution is
        # test_physics_derived_rtp_stays_safe_across_full_drop_range below.
        for rows, risk_tables in FREE_DROP_MULTIPLIER_TABLES.items():
            for risk_level, table in risk_tables.items():
                self.assertEqual(len(table), rows + 1)
                self.assertEqual(table, table[::-1], f'{rows}/{risk_level} is not symmetric')

    def test_physics_derived_rtp_stays_safe_across_full_drop_range(self):
        """
        Unlike the old (removed) abstract-path model, Free Drop's outcome
        distribution now comes directly from FREE_DROP_PHYSICS_TABLE - the
        real, offline-verified Matter.js empirical distribution (see
        free_drop_constants.py and scripts/generate-free-drop-physics-table.ts).
        This computes RTP from that *actual* live data, for every bucket
        across the full legal drop range and every risk tier, so it catches
        both a bad multiplier table AND a skewed physics distribution.
        """
        worst = 0.0
        worst_id = None
        for rows, buckets in FREE_DROP_PHYSICS_TABLE.items():
            for bucket_index, slot_weights in buckets.items():
                total_weight = sum(entry['weight'] for entry in slot_weights.values())
                self.assertGreater(total_weight, 0, f'rows={rows} bucket={bucket_index} has no reachable slots')
                for risk_level, table in FREE_DROP_MULTIPLIER_TABLES[rows].items():
                    ev = sum(entry['weight'] * table[slot] for slot, entry in slot_weights.items()) / total_weight
                    if ev > worst:
                        worst = ev
                        worst_id = (rows, bucket_index, risk_level)

        self.assertLess(worst, 0.99, f'Worst-case physics-derived EV too high: {worst} ({worst_id})')

    def test_extreme_and_center_buckets_individually_stay_under_full_rtp(self):
        # Explicit spot-check on the buckets called out by the design brief
        # (far left/right and center), on top of the exhaustive sweep above.
        for rows, buckets in FREE_DROP_PHYSICS_TABLE.items():
            for bucket_index in {0, DROP_BUCKETS // 2, DROP_BUCKETS - 1}:
                slot_weights = buckets[bucket_index]
                total_weight = sum(entry['weight'] for entry in slot_weights.values())
                for risk_level, table in FREE_DROP_MULTIPLIER_TABLES[rows].items():
                    ev = sum(entry['weight'] * table[slot] for slot, entry in slot_weights.items()) / total_weight
                    self.assertLess(ev, 1.0, f'rows={rows} bucket={bucket_index} risk={risk_level}: EV {ev} >= 100%')


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

    def test_outcome_is_always_a_slot_physically_reachable_from_the_bucket(self):
        # The core correctness guarantee this whole rework exists for: the
        # picked slot must always be a key in that exact bucket's verified
        # table - never invented, never borrowed from a neighboring bucket.
        for drop_position in (-1.0, -0.6, -0.2, 0.0, 0.35, 0.7, 1.0):
            for _ in range(20):
                bucket_index, slot_index, physics_seed = pick_free_drop_outcome(8, drop_position)
                self.assertEqual(bucket_index, bucket_index_for_drop_position(drop_position))
                reachable = get_physics_table(8, bucket_index)
                self.assertIn(slot_index, reachable, f'slot {slot_index} not reachable from bucket {bucket_index}')
                self.assertIn(physics_seed, reachable[slot_index]['seeds'])

    def test_physics_seed_and_slot_are_stored(self):
        round_obj = play_free_drop_round(self.user, rows=8, risk_level='low', wager_amount=100, drop_position=0.5)

        self.assertEqual(round_obj.mode, PlinkoRound.MODE_FREE_DROP)
        self.assertIsNotNone(round_obj.physics_seed)
        bucket_index = bucket_index_for_drop_position(0.5)
        reachable = get_physics_table(8, bucket_index)
        self.assertIn(round_obj.slot_index, reachable)
        self.assertIn(round_obj.physics_seed, reachable[round_obj.slot_index]['seeds'])
        self.assertEqual(
            round_obj.multiplier,
            Decimal(str(FREE_DROP_MULTIPLIER_TABLES[8]['low'][round_obj.slot_index])),
        )

    def test_repeated_rounds_from_same_position_vary(self):
        # Same drop_position across many rounds should not always produce
        # the exact same (slot, seed) - real server-side entropy per round.
        outcomes = {
            (round_obj.slot_index, round_obj.physics_seed)
            for round_obj in (
                play_free_drop_round(self.user, rows=8, risk_level='low', wager_amount=5, drop_position=0.35)
                for _ in range(40)
            )
        }
        self.assertGreater(len(outcomes), 1)

    def test_drop_position_statistically_shifts_landing_distribution(self):
        # Requirement: a far-left drop should statistically favor left-side
        # slots (lower slot_index) versus a far-right drop, without going
        # through play_free_drop_round (no points spent) - pick_free_drop_outcome
        # is the same weighted draw the real flow uses.
        def average_slot(position, samples=250):
            total = sum(pick_free_drop_outcome(8, position)[1] for _ in range(samples))
            return total / samples

        self.assertLess(average_slot(-1.0), average_slot(1.0))

    def test_drop_position_clamped_beyond_range(self):
        round_obj = play_free_drop_round(self.user, rows=8, risk_level='low', wager_amount=10, drop_position=5.0)
        self.assertEqual(round_obj.drop_position, 1.0)

    def test_ledger_entry_records_mode_drop_position_and_seed(self):
        round_obj = play_free_drop_round(self.user, rows=8, risk_level='low', wager_amount=100, drop_position=-0.3)

        entry = round_obj.ledger_entry
        self.assertIsNotNone(entry)
        self.assertEqual(entry.metadata['game'], 'plinko')
        self.assertEqual(entry.metadata['mode'], 'free_drop')
        self.assertEqual(entry.metadata['drop_position'], '-0.3')
        self.assertEqual(entry.metadata['physics_seed'], round_obj.physics_seed)

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

    def test_classic_round_does_not_gain_drop_position_or_physics_seed(self):
        # Cross-mode isolation guard: Classic rounds must keep drop_position/
        # physics_seed null - Free Drop's fields should never leak onto
        # Classic play, which still uses its own untouched path-based flow.
        with mock.patch('plinko.services.generate_path', return_value=[1] * 8):
            classic_round = play_round(self.user, rows=8, risk_level='low', wager_amount=10)
        self.assertEqual(classic_round.mode, PlinkoRound.MODE_CLASSIC)
        self.assertIsNone(classic_round.drop_position)
        self.assertIsNone(classic_round.physics_seed)


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
        self.assertEqual(response.data['multipliers'][8]['low'][0], FREE_DROP_MULTIPLIER_TABLES[8]['low'][0])

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

    def test_materially_out_of_range_positions_rejected(self):
        # 1.2 / -1.4 aren't float-precision noise - genuinely invalid input,
        # must still be rejected with a clear field-level error.
        self.client.force_authenticate(user=self.player)
        for bad_value in (1.2, -1.4):
            response = self.client.post(
                reverse('plinko-free-drop-play'),
                {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': bad_value},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn('drop_position', response.data.get('errors', response.data))
        self.assertEqual(PlinkoRound.objects.count(), 0)

    def test_extreme_left_position_is_valid(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': -1.0},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['drop_position'], -1.0)

    def test_extreme_right_position_is_valid(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': 1.0},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['drop_position'], 1.0)

    def test_microscopic_float_overflow_is_tolerated_and_clamped(self):
        # The actual bug this covers: client-side normalization math can
        # occasionally produce e.g. -1.0000000000000002 for a drop the
        # player placed exactly at the extreme edge. That must not 400.
        self.client.force_authenticate(user=self.player)
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': -1.0000000000000002},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['drop_position'], -1.0)

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

    def test_successful_play_returns_round_with_mode_drop_position_and_seed(self):
        self.client.force_authenticate(user=self.player)
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': 0.4},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['mode'], 'free_drop')
        self.assertEqual(response.data['drop_position'], 0.4)
        self.assertIsNotNone(response.data['physics_seed'])
        bucket_index = bucket_index_for_drop_position(0.4)
        reachable = get_physics_table(8, bucket_index)
        self.assertIn(response.data['slot_index'], reachable)
        self.assertEqual(PlinkoRound.objects.filter(user=self.player, mode='free_drop').count(), 1)

    def test_client_cannot_submit_its_own_slot_multiplier_or_payout(self):
        # FreeDropPlayRequestSerializer doesn't declare these fields at all,
        # so DRF silently ignores them - the server-computed values must
        # come out instead, never whatever the client tried to inject.
        self.client.force_authenticate(user=self.player)
        response = self.client.post(
            reverse('plinko-free-drop-play'),
            {
                'rows': 8, 'risk_level': 'low', 'wager_amount': 10, 'drop_position': 0.0,
                'slot_index': 999, 'multiplier': '9999.00', 'payout_amount': '9999.00',
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.data['multiplier'], '9999.00')
        self.assertNotEqual(response.data['payout_amount'], '9999.00')
        bucket_index = bucket_index_for_drop_position(0.0)
        self.assertIn(response.data['slot_index'], get_physics_table(8, bucket_index))

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

    def test_history_endpoint_includes_both_modes_with_physics_seed(self):
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
        by_mode = {row['mode']: row for row in response.data}
        self.assertIsNotNone(by_mode['free_drop']['physics_seed'])
        self.assertIsNone(by_mode['classic']['physics_seed'])


class FreeDropPhysicsTableValidationTests(TestCase):
    def test_live_table_passes_its_own_validator(self):
        # The table already loaded successfully at import time (this test
        # module wouldn't have imported otherwise) - re-running the
        # validator here just pins that behavior as an explicit regression
        # guard rather than relying on import-time side effects alone.
        self.assertEqual(_validate_physics_table(FREE_DROP_PHYSICS_TABLE), FREE_DROP_PHYSICS_TABLE)

    def test_every_bucket_has_at_least_one_seed_per_listed_slot(self):
        for rows, buckets in FREE_DROP_PHYSICS_TABLE.items():
            self.assertEqual(len(buckets), DROP_BUCKETS)
            for bucket_index, slots in buckets.items():
                self.assertGreater(len(slots), 0, f'rows={rows} bucket={bucket_index} has no reachable slots')
                for slot_index, entry in slots.items():
                    self.assertGreaterEqual(slot_index, 0)
                    self.assertLessEqual(slot_index, rows)
                    self.assertGreater(len(entry['seeds']), 0)
                    self.assertTrue(0 < entry['weight'] <= 1)

    def test_validator_rejects_missing_buckets(self):
        broken = {8: {i: {0: {'seeds': [1], 'weight': 1.0}} for i in range(DROP_BUCKETS - 1)}}  # one bucket short
        with self.assertRaises(ValueError):
            _validate_physics_table(broken)

    def test_validator_rejects_empty_bucket(self):
        broken = {8: {i: ({} if i == 0 else {0: {'seeds': [1], 'weight': 1.0}}) for i in range(DROP_BUCKETS)}}
        with self.assertRaises(ValueError):
            _validate_physics_table(broken)

    def test_validator_rejects_out_of_range_slot(self):
        broken = {8: {i: {99: {'seeds': [1], 'weight': 1.0}} for i in range(DROP_BUCKETS)}}
        with self.assertRaises(ValueError):
            _validate_physics_table(broken)

    def test_validator_rejects_empty_seed_list(self):
        broken = {8: {i: {0: {'seeds': [], 'weight': 1.0}} for i in range(DROP_BUCKETS)}}
        with self.assertRaises(ValueError):
            _validate_physics_table(broken)

    def test_validator_rejects_invalid_weight(self):
        broken = {8: {i: {0: {'seeds': [1], 'weight': 1.5}} for i in range(DROP_BUCKETS)}}
        with self.assertRaises(ValueError):
            _validate_physics_table(broken)

    def test_selected_seed_maps_to_the_stored_slot_across_many_positions(self):
        # Cross-check pick_free_drop_outcome() against the table it reads
        # from - the chosen seed must always belong to the chosen slot's
        # seed pool for that exact bucket, for every legal drop position.
        for drop_position in (-1.0, -0.75, -0.3, 0.0, 0.2, 0.6, 1.0):
            for _ in range(10):
                bucket_index, slot_index, physics_seed = pick_free_drop_outcome(8, drop_position)
                table = get_physics_table(8, bucket_index)
                self.assertIn(slot_index, table)
                self.assertIn(physics_seed, table[slot_index]['seeds'])


class PlinkoGameplayXPHookTests(TestCase):
    """
    Relies on the seeded XPAction rows from xp/migrations/0002_seed_xp_actions.py:
    qualified_gameplay (+2 XP, max_awards_per_day=25) and
    daily_challenge_rounds (+30 XP, challenge_target_count=3, sourced from
    qualified_gameplay). Covers both play_round (Classic) and
    play_free_drop_round (Free Drop) since both call the same
    plinko.xp_hooks.grant_gameplay_xp() helper.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='xp-gameplay-player',
            email='xp-gameplay-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        Game.objects.filter(slug='plinko').update(is_active=True)
        PointsBalance.objects.create(user=self.user, balance=100000)

    def test_qualified_gameplay_xp_awarded_per_round_regardless_of_wager_size(self):
        play_round(self.user, rows=8, risk_level='low', wager_amount=5)
        play_round(self.user, rows=8, risk_level='low', wager_amount=10)
        self.assertEqual(XPBalance.objects.get(user=self.user).total_xp, 4)  # 2 rounds x 2 XP
        self.assertEqual(
            XPLedgerEntry.objects.filter(user=self.user, action__slug='qualified_gameplay').count(), 2,
        )

    def test_qualified_gameplay_xp_stops_at_daily_cap_without_blocking_play(self):
        for _ in range(30):
            round_obj = play_round(self.user, rows=8, risk_level='low', wager_amount=5)
        self.assertIsNotNone(round_obj)  # the 30th round still succeeded despite the 25/day XP cap
        self.assertEqual(
            XPLedgerEntry.objects.filter(user=self.user, action__slug='qualified_gameplay').count(), 25,
        )
        self.assertEqual(PlinkoRound.objects.filter(user=self.user).count(), 30)

    def test_daily_challenge_fires_once_after_three_rounds(self):
        for _ in range(3):
            play_round(self.user, rows=8, risk_level='low', wager_amount=5)
        self.assertEqual(
            XPLedgerEntry.objects.filter(user=self.user, action__slug='daily_challenge_rounds').count(), 1,
        )
        # Total: 3 rounds x 2 XP (qualified_gameplay) + 30 XP (challenge) = 36
        self.assertEqual(XPBalance.objects.get(user=self.user).total_xp, 36)

        play_round(self.user, rows=8, risk_level='low', wager_amount=5)  # a 4th round must not re-fire the challenge
        self.assertEqual(
            XPLedgerEntry.objects.filter(user=self.user, action__slug='daily_challenge_rounds').count(), 1,
        )

    def test_free_drop_rounds_also_award_gameplay_xp(self):
        play_free_drop_round(self.user, rows=8, risk_level='low', wager_amount=5, drop_position=0.0)
        self.assertEqual(
            XPLedgerEntry.objects.filter(user=self.user, action__slug='qualified_gameplay').count(), 1,
        )

    def test_xp_award_never_blocks_or_rolls_back_the_wager(self):
        # Even with a misconfigured/deactivated XPAction, the round and
        # points settlement must succeed unaffected.
        from xp.models import XPAction
        XPAction.objects.filter(slug='qualified_gameplay').update(is_active=False)
        balance_before = PointsBalance.objects.get(user=self.user).balance
        round_obj = play_round(self.user, rows=8, risk_level='low', wager_amount=5)
        self.assertIsNotNone(round_obj.id)
        self.assertNotEqual(PointsBalance.objects.get(user=self.user).balance, balance_before)  # wager still settled
