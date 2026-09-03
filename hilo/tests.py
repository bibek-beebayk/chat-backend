from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from games.models import Game
from points.models import PointsBalance
from points.services import InsufficientPoints
from .constants import HOUSE_EDGE, MAX_MULTIPLIER, MAX_STEPS, MIN_STEP_MULTIPLIER, RANKS
from .models import HiLoRound, HiLoStep
from .services import (
    ActiveRoundExists,
    ImpossiblePrediction,
    NoActiveRound,
    NothingToCashOut,
    RoundAlreadyResolved,
    StaleStep,
    apply_step,
    cash_out,
    draw_card,
    evaluate,
    outcome_counts,
    payout_for,
    predict,
    probability,
    quote,
    rank_value,
    start_round,
    step_multiplier,
)


class HiLoMathTests(TestCase):
    """Pure-function tests - no DB, no round lifecycle."""

    def test_ace_is_high_and_ranks_are_ordered(self):
        values = [rank_value(r) for r in RANKS]
        self.assertEqual(values, sorted(values))
        self.assertEqual(rank_value('2'), 2)
        self.assertEqual(rank_value('A'), 14)
        self.assertGreater(rank_value('A'), rank_value('K'))

    def test_probabilities_sum_to_one_for_every_rank(self):
        for rank in RANKS:
            counts = outcome_counts(rank)
            self.assertEqual(counts['higher'] + counts['lower'] + counts['push'], len(RANKS))
            # Compared with a tolerance, not exactly: a thirteenth is a
            # repeating decimal, so the three parts can only sum to 1
            # within Decimal's working precision. The exact invariant is
            # the integer count check above.
            total = probability(rank, 'higher') + probability(rank, 'lower') + Decimal(1) / Decimal(len(RANKS))
            self.assertLess(abs(total - Decimal(1)), Decimal('0.000000001'))

    def test_only_the_two_extreme_ranks_have_an_impossible_direction(self):
        with self.assertRaises(ImpossiblePrediction):
            step_multiplier('2', 'lower')
        with self.assertRaises(ImpossiblePrediction):
            step_multiplier('A', 'higher')
        for rank in RANKS[1:-1]:
            step_multiplier(rank, 'higher')
            step_multiplier(rank, 'lower')
        # The other direction on those two ranks stays playable, so a round
        # can never dead-end.
        self.assertIsNotNone(step_multiplier('2', 'higher'))
        self.assertIsNotNone(step_multiplier('A', 'lower'))

    def test_riskier_predictions_pay_more(self):
        # Higher gets steadily riskier - and steadily better paid - as the
        # face-up card climbs.
        payouts = [step_multiplier(rank, 'higher') for rank in RANKS[:-1]]
        for a, b in zip(payouts, payouts[1:]):
            self.assertLess(a, b)

    def test_the_symmetric_card_pays_both_sides_equally(self):
        # 8 has six ranks above and six below.
        self.assertEqual(step_multiplier('8', 'higher'), step_multiplier('8', 'lower'))

    def test_a_correct_prediction_never_lowers_the_multiplier(self):
        # The reason MIN_STEP_MULTIPLIER exists: on a 2 the HIGHER branch is
        # a certainty once pushes are excluded, so the raw priced step would
        # be (1 - HOUSE_EDGE) = 0.97 and winning would shrink the round.
        self.assertEqual(step_multiplier('2', 'higher'), MIN_STEP_MULTIPLIER)
        self.assertEqual(step_multiplier('A', 'lower'), MIN_STEP_MULTIPLIER)
        for rank in RANKS:
            for direction in ('higher', 'lower'):
                if outcome_counts(rank)[direction] == 0:
                    continue
                self.assertGreater(step_multiplier(rank, direction), Decimal('1.00'))

    def test_expected_return_per_prediction_is_the_configured_house_edge(self):
        """
        The core RTP property: conditioned on a non-push result, staking 1
        unit on any card/direction returns (1 - HOUSE_EDGE) in expectation.
        Checked against exact probabilities rather than simulation, so it
        can't flake. The two floored extremes are excluded - that floor is
        a deliberate, documented deviation (see the test above).
        """
        for rank in RANKS:
            for direction in ('higher', 'lower'):
                counts = outcome_counts(rank)
                if counts[direction] == 0 or counts[direction] == counts['higher'] + counts['lower']:
                    continue  # impossible, or the floored certainty
                p_effective = Decimal(counts[direction]) / Decimal(counts['higher'] + counts['lower'])
                expected = p_effective * step_multiplier(rank, direction)
                # Quantizing the step ROUND_DOWN can only ever move the
                # return slightly *below* the nominal edge, never above it.
                # The upper bound carries a tiny epsilon for the same
                # repeating-decimal reason as the test above - p_effective
                # is a ratio of small integers that Decimal can't represent
                # exactly, so an exact-equality case lands a few units in
                # the last place either side.
                self.assertLessEqual(expected, Decimal(1) - HOUSE_EDGE + Decimal('0.000000001'))
                self.assertGreater(expected, Decimal(1) - HOUSE_EDGE - Decimal('0.02'))

    def test_evaluate_covers_win_push_and_loss(self):
        self.assertEqual(evaluate('7', 'J', 'higher'), HiLoStep.OUTCOME_WIN)
        self.assertEqual(evaluate('7', '3', 'higher'), HiLoStep.OUTCOME_LOSS)
        self.assertEqual(evaluate('7', '7', 'higher'), HiLoStep.OUTCOME_PUSH)
        self.assertEqual(evaluate('7', '7', 'lower'), HiLoStep.OUTCOME_PUSH)
        self.assertEqual(evaluate('J', '5', 'lower'), HiLoStep.OUTCOME_WIN)
        self.assertEqual(evaluate('J', 'K', 'lower'), HiLoStep.OUTCOME_LOSS)

    def test_accumulated_multiplier_is_capped(self):
        self.assertEqual(apply_step(Decimal('99.00'), Decimal('11.64')), MAX_MULTIPLIER)

    def test_payout_respects_the_separate_payout_cap(self):
        from .constants import MAX_PAYOUT
        self.assertEqual(payout_for(Decimal('1000'), MAX_MULTIPLIER), MAX_PAYOUT)
        self.assertEqual(payout_for(Decimal('10'), Decimal('2.50')), Decimal('25.00'))

    def test_quote_marks_the_impossible_direction_unavailable(self):
        two = quote('2')
        self.assertFalse(two['lower']['available'])
        self.assertIsNone(two['lower']['multiplier'])
        self.assertTrue(two['higher']['available'])

    def test_draw_card_only_produces_valid_cards(self):
        from .constants import SUITS
        for _ in range(500):
            card = draw_card()
            self.assertIn(card['rank'], RANKS)
            self.assertIn(card['suit'], SUITS)


class HiLoRoundTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='hilo-player',
            email='hilo-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        Game.objects.update_or_create(slug='hilo', defaults={'name': 'Rollin Hi-Lo', 'is_active': True})
        PointsBalance.objects.create(user=self.user, balance=1000)

    def _round_on(self, rank, suit='hearts', wager='100'):
        """Starts a round with a known face-up card."""
        with mock.patch('hilo.services.draw_card', return_value={'rank': rank, 'suit': suit}):
            round_obj, _ = start_round(self.user, wager_amount=Decimal(wager))
        return round_obj

    def _predict(self, round_obj, direction, next_rank, next_suit='spades'):
        with mock.patch('hilo.services.draw_card', return_value={'rank': next_rank, 'suit': next_suit}):
            return predict(self.user, direction=direction, step_index=round_obj.steps_taken)

    # --- start ---

    def test_start_debits_immediately_and_deals_a_card(self):
        round_obj = self._round_on('7')
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, Decimal('900'))
        self.assertEqual(round_obj.status, HiLoRound.STATUS_ACTIVE)
        self.assertEqual(round_obj.current_rank, '7')
        self.assertEqual(round_obj.multiplier, Decimal('1.00'))

    def test_insufficient_balance_creates_no_round(self):
        PointsBalance.objects.filter(user=self.user).update(balance=5)
        with self.assertRaises(InsufficientPoints):
            start_round(self.user, wager_amount=Decimal('100'))
        self.assertEqual(HiLoRound.objects.count(), 0)

    def test_second_round_while_one_is_active_is_rejected_and_refunds_nothing(self):
        self._round_on('7')
        with self.assertRaises(ActiveRoundExists):
            start_round(self.user, wager_amount=Decimal('100'))
        # The rejected start's debit rolled back with it - only the first
        # round's wager left the balance.
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, Decimal('900'))
        self.assertEqual(HiLoRound.objects.count(), 1)

    def test_replayed_client_request_id_does_not_double_charge(self):
        with mock.patch('hilo.services.draw_card', return_value={'rank': '7', 'suit': 'hearts'}):
            first, created_first = start_round(self.user, wager_amount=Decimal('100'), client_request_id='abc')
            second, created_second = start_round(self.user, wager_amount=Decimal('100'), client_request_id='abc')
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.id, second.id)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, Decimal('900'))

    # --- predict ---

    def test_a_win_raises_the_multiplier_and_the_streak(self):
        round_obj = self._round_on('7')
        expected_step = step_multiplier('7', 'higher')
        round_obj, step = self._predict(round_obj, 'higher', 'J')
        self.assertEqual(step.outcome, HiLoStep.OUTCOME_WIN)
        self.assertEqual(round_obj.multiplier, expected_step)
        self.assertEqual(round_obj.streak, 1)
        self.assertEqual(round_obj.current_rank, 'J')
        self.assertEqual(round_obj.status, HiLoRound.STATUS_ACTIVE)

    def test_a_push_advances_the_card_but_changes_nothing_else(self):
        round_obj = self._round_on('8', suit='clubs')
        round_obj, _ = self._predict(round_obj, 'higher', 'J')
        multiplier_before, streak_before = round_obj.multiplier, round_obj.streak

        round_obj, step = self._predict(round_obj, 'higher', 'J', next_suit='diamonds')
        self.assertEqual(step.outcome, HiLoStep.OUTCOME_PUSH)
        self.assertEqual(step.step_multiplier, Decimal('1.00'))
        self.assertEqual(round_obj.multiplier, multiplier_before)
        self.assertEqual(round_obj.streak, streak_before)
        self.assertEqual(round_obj.status, HiLoRound.STATUS_ACTIVE)
        self.assertEqual(round_obj.current_suit, 'diamonds')  # advanced to the new card

    def test_a_loss_ends_the_round_with_no_payout(self):
        round_obj = self._round_on('7')
        round_obj, step = self._predict(round_obj, 'higher', '3')
        self.assertEqual(step.outcome, HiLoStep.OUTCOME_LOSS)
        self.assertEqual(round_obj.status, HiLoRound.STATUS_BUSTED)
        self.assertEqual(round_obj.payout_amount, Decimal('0.00'))
        self.assertIsNotNone(round_obj.resolved_at)
        # No credit ever happened - the balance is still just wager-deducted.
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, Decimal('900'))

    def test_a_stale_step_index_draws_no_card(self):
        round_obj = self._round_on('7')
        round_obj, _ = self._predict(round_obj, 'higher', 'J')
        steps_before = round_obj.steps_taken
        with self.assertRaises(StaleStep):
            predict(self.user, direction='higher', step_index=0)
        round_obj.refresh_from_db()
        self.assertEqual(round_obj.steps_taken, steps_before)
        self.assertEqual(round_obj.steps.count(), 1)

    def test_impossible_prediction_is_rejected_and_leaves_the_round_untouched(self):
        round_obj = self._round_on('2')
        with self.assertRaises(ImpossiblePrediction):
            predict(self.user, direction='lower', step_index=0)
        round_obj.refresh_from_db()
        self.assertEqual(round_obj.steps_taken, 0)
        self.assertEqual(round_obj.current_rank, '2')

    def test_predicting_on_a_resolved_round_is_rejected(self):
        round_obj = self._round_on('7')
        round_obj, _ = self._predict(round_obj, 'higher', '3')  # bust
        with self.assertRaises(RoundAlreadyResolved):
            predict(self.user, direction='higher', step_index=1)

    def test_predicting_with_no_round_at_all_raises(self):
        with self.assertRaises(NoActiveRound):
            predict(self.user, direction='higher', step_index=0)

    def test_every_prediction_is_recorded_as_a_step(self):
        round_obj = self._round_on('7')
        round_obj, _ = self._predict(round_obj, 'higher', 'J')
        round_obj, _ = self._predict(round_obj, 'lower', '5')
        round_obj, _ = self._predict(round_obj, 'higher', 'K')
        steps = list(round_obj.steps.all())
        self.assertEqual([s.step_index for s in steps], [0, 1, 2])
        self.assertEqual([s.outcome for s in steps], ['win', 'win', 'win'])
        self.assertEqual(steps[-1].multiplier_after, round_obj.multiplier)

    # --- cash out ---

    def test_cash_out_credits_wager_times_multiplier(self):
        round_obj = self._round_on('7')
        round_obj, _ = self._predict(round_obj, 'higher', 'J')
        expected = payout_for(round_obj.wager_amount, round_obj.multiplier)

        round_obj = cash_out(self.user)
        self.assertEqual(round_obj.status, HiLoRound.STATUS_CASHED_OUT)
        self.assertEqual(round_obj.payout_amount, expected)
        self.assertFalse(round_obj.capped)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, Decimal('900') + expected)

    def test_cash_out_before_any_correct_prediction_is_rejected(self):
        self._round_on('7')
        with self.assertRaises(NothingToCashOut):
            cash_out(self.user)

    def test_cash_out_after_only_a_push_is_still_rejected(self):
        round_obj = self._round_on('8')
        self._predict(round_obj, 'higher', '8')
        with self.assertRaises(NothingToCashOut):
            cash_out(self.user)

    def test_a_second_cash_out_does_not_pay_twice(self):
        round_obj = self._round_on('7')
        self._predict(round_obj, 'higher', 'J')
        cash_out(self.user)
        balance_after_first = PointsBalance.objects.get(user=self.user).balance

        with self.assertRaises(RoundAlreadyResolved):
            cash_out(self.user)
        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, balance_after_first)

    def test_cash_out_with_no_round_at_all_raises(self):
        with self.assertRaises(NoActiveRound):
            cash_out(self.user)

    # --- ceilings ---

    def test_hitting_the_multiplier_cap_force_settles_the_round(self):
        round_obj = self._round_on('7')
        HiLoRound.objects.filter(pk=round_obj.pk).update(multiplier=Decimal('99.00'))
        round_obj.refresh_from_db()
        # K -> higher pays 11.64x, which takes 99.00 past the 100x cap.
        HiLoRound.objects.filter(pk=round_obj.pk).update(current_rank='K')
        round_obj.refresh_from_db()
        round_obj, _ = self._predict(round_obj, 'higher', 'A')

        self.assertEqual(round_obj.status, HiLoRound.STATUS_CASHED_OUT)
        self.assertTrue(round_obj.capped)
        self.assertEqual(round_obj.multiplier, MAX_MULTIPLIER)
        self.assertGreater(round_obj.payout_amount, Decimal('0'))

    def test_hitting_the_step_limit_force_settles_the_round(self):
        round_obj = self._round_on('7')
        round_obj, _ = self._predict(round_obj, 'higher', 'J')
        HiLoRound.objects.filter(pk=round_obj.pk).update(steps_taken=MAX_STEPS - 1, current_rank='7')
        round_obj.refresh_from_db()
        round_obj, _ = self._predict(round_obj, 'higher', 'J')
        self.assertEqual(round_obj.status, HiLoRound.STATUS_CASHED_OUT)
        self.assertTrue(round_obj.capped)


class HiLoApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='hilo-api-player',
            email='hilo-api-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        Game.objects.update_or_create(slug='hilo', defaults={'name': 'Rollin Hi-Lo', 'is_active': True})
        PointsBalance.objects.create(user=self.user, balance=1000)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_config_exposes_the_pricing_inputs(self):
        response = self.client.get(reverse('hilo-config'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['house_edge'], str(HOUSE_EDGE))
        self.assertEqual(response.data['ranks'], RANKS)

    def test_play_returns_a_round_with_a_live_quote_for_both_sides(self):
        with mock.patch('hilo.services.draw_card', return_value={'rank': '9', 'suit': 'spades'}):
            response = self.client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['current_card'], {'rank': '9', 'suit': 'spades'})
        self.assertTrue(response.data['odds']['higher']['available'])
        self.assertTrue(response.data['odds']['lower']['available'])
        self.assertFalse(response.data['can_cash_out'])

    def test_staff_accounts_cannot_play(self):
        staff = get_user_model().objects.create_user(
            username='hilo-staff', email='hilo-staff@example.com',
            password='test-pass-123', user_type='staff',
        )
        client = APIClient()
        client.force_authenticate(staff)
        response = client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_duplicate_play_returns_409_with_the_active_round(self):
        with mock.patch('hilo.services.draw_card', return_value={'rank': '9', 'suit': 'spades'}):
            self.client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
            response = self.client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertIn('active_round', response.data)

    def test_current_restores_an_in_flight_round_and_is_null_otherwise(self):
        self.assertIsNone(self.client.get(reverse('hilo-current')).data)
        with mock.patch('hilo.services.draw_card', return_value={'rank': '9', 'suit': 'spades'}):
            self.client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
        response = self.client.get(reverse('hilo-current'))
        self.assertEqual(response.data['current_card']['rank'], '9')

    def test_predict_returns_the_step_and_the_resulting_round(self):
        with mock.patch('hilo.services.draw_card', return_value={'rank': '7', 'suit': 'spades'}):
            self.client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
        with mock.patch('hilo.services.draw_card', return_value={'rank': 'K', 'suit': 'hearts'}):
            response = self.client.post(
                reverse('hilo-predict'), {'prediction': 'higher', 'step_index': 0}, format='json',
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['step']['outcome'], 'win')
        self.assertEqual(response.data['step']['to_card'], {'rank': 'K', 'suit': 'hearts'})
        self.assertTrue(response.data['round']['can_cash_out'])

    def test_a_duplicate_predict_returns_409_and_resyncs_rather_than_redrawing(self):
        with mock.patch('hilo.services.draw_card', return_value={'rank': '7', 'suit': 'spades'}):
            self.client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
        with mock.patch('hilo.services.draw_card', return_value={'rank': 'K', 'suit': 'hearts'}):
            self.client.post(reverse('hilo-predict'), {'prediction': 'higher', 'step_index': 0}, format='json')
            response = self.client.post(
                reverse('hilo-predict'), {'prediction': 'higher', 'step_index': 0}, format='json',
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['round']['steps_taken'], 1)
        self.assertEqual(HiLoStep.objects.count(), 1)

    def test_impossible_prediction_is_a_400(self):
        with mock.patch('hilo.services.draw_card', return_value={'rank': 'A', 'suit': 'spades'}):
            self.client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
        response = self.client.post(
            reverse('hilo-predict'), {'prediction': 'higher', 'step_index': 0}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_predict_requires_a_step_index(self):
        with mock.patch('hilo.services.draw_card', return_value={'rank': '7', 'suit': 'spades'}):
            self.client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
        response = self.client.post(reverse('hilo-predict'), {'prediction': 'higher'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_a_second_cashout_request_is_idempotent(self):
        with mock.patch('hilo.services.draw_card', return_value={'rank': '7', 'suit': 'spades'}):
            self.client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
        with mock.patch('hilo.services.draw_card', return_value={'rank': 'K', 'suit': 'hearts'}):
            self.client.post(reverse('hilo-predict'), {'prediction': 'higher', 'step_index': 0}, format='json')

        first = self.client.post(reverse('hilo-cashout'), {}, format='json')
        second = self.client.post(reverse('hilo-cashout'), {}, format='json')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['payout_amount'], second.data['payout_amount'])

    def test_history_and_stats_reflect_resolved_rounds(self):
        with mock.patch('hilo.services.draw_card', return_value={'rank': '7', 'suit': 'spades'}):
            self.client.post(reverse('hilo-play'), {'wager_amount': '10'}, format='json')
        with mock.patch('hilo.services.draw_card', return_value={'rank': '3', 'suit': 'hearts'}):
            self.client.post(reverse('hilo-predict'), {'prediction': 'higher', 'step_index': 0}, format='json')

        history = self.client.get(reverse('hilo-history'))
        self.assertEqual(len(history.data), 1)
        self.assertEqual(history.data[0]['status'], 'busted')
        self.assertEqual(len(history.data[0]['steps']), 1)

        stats = self.client.get(reverse('hilo-stats'))
        self.assertEqual(stats.data['rounds_played'], 1)
        self.assertEqual(stats.data['total_predictions'], 1)
        self.assertEqual(stats.data['incorrect_predictions'], 1)
        self.assertEqual(stats.data['total_wagered'], '10.00')


class HiLoXPTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='hilo-xp-player',
            email='hilo-xp-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        Game.objects.update_or_create(slug='hilo', defaults={'name': 'Rollin Hi-Lo', 'is_active': True})
        PointsBalance.objects.create(user=self.user, balance=100000)

    def test_a_capped_xp_award_never_rolls_back_the_settlement(self):
        # hilo.xp_hooks.grant_hilo_xp is now purely resolution-specific
        # (gameplay/challenge XP for just playing a round moved to
        # points.services._grant_round_xp at bet-placement time - see
        # HiLoRound's docstring) - so this needs a scenario that actually
        # reaches one of what's left, a cashout-threshold achievement:
        # Q -> A is a single win that clears both the 2x and 5x thresholds.
        from xp.services import DailyCapExceeded

        with mock.patch('hilo.services.draw_card', return_value={'rank': 'Q', 'suit': 'spades'}):
            round_obj, _ = start_round(self.user, wager_amount=Decimal('100'))
        with mock.patch('hilo.services.draw_card', return_value={'rank': 'A', 'suit': 'hearts'}):
            predict(self.user, direction='higher', step_index=0)
        self.assertGreaterEqual(HiLoRound.objects.get(pk=round_obj.pk).multiplier, Decimal('5'))

        with mock.patch('hilo.xp_hooks.award_xp', side_effect=DailyCapExceeded('hilo_cashout_above_2x')):
            round_obj = cash_out(self.user)

        self.assertEqual(round_obj.status, HiLoRound.STATUS_CASHED_OUT)
        self.assertGreater(round_obj.payout_amount, Decimal('0'))

    def test_hooks_run_once_per_resolved_round(self):
        with mock.patch('hilo.services.draw_card', return_value={'rank': '7', 'suit': 'spades'}):
            start_round(self.user, wager_amount=Decimal('100'))
        with mock.patch('hilo.xp_hooks.grant_hilo_xp') as hook:
            with mock.patch('hilo.services.draw_card', return_value={'rank': '3', 'suit': 'hearts'}):
                predict(self.user, direction='higher', step_index=0)
            self.assertEqual(hook.call_count, 1)
