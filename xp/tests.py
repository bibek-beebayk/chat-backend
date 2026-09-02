from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from notifications.models import Notification
from .models import XPAction, XPBalance, XPLedgerEntry
from points.models import PointsBalance, PointsLedgerEntry
from .ranks import RANK_THRESHOLDS, next_rank_for_xp, rank_for_xp, sub_level_for_xp, sub_ranges_for_tier
from .services import ChallengeNotYetEligible, DailyCapExceeded, RANK_UP_BONUS_RP, apply_adjustment, award_xp


class RankThresholdTests(TestCase):
    def test_rank_for_xp_at_exact_boundaries(self):
        for tier in RANK_THRESHOLDS:
            self.assertEqual(rank_for_xp(tier.min_xp).slug, tier.slug)

    def test_rank_for_xp_just_below_boundary_stays_previous_tier(self):
        for previous, tier in zip(RANK_THRESHOLDS, RANK_THRESHOLDS[1:]):
            self.assertEqual(rank_for_xp(tier.min_xp - 1).slug, previous.slug)

    def test_rank_for_xp_zero_is_first_tier(self):
        self.assertEqual(rank_for_xp(0).slug, RANK_THRESHOLDS[0].slug)

    def test_next_rank_for_xp_top_tier_returns_none(self):
        top = RANK_THRESHOLDS[-1]
        self.assertIsNone(next_rank_for_xp(top.min_xp))
        self.assertIsNone(next_rank_for_xp(top.min_xp + 100000))

    def test_next_rank_for_xp_returns_the_following_tier(self):
        first, second = RANK_THRESHOLDS[0], RANK_THRESHOLDS[1]
        self.assertEqual(next_rank_for_xp(first.min_xp).slug, second.slug)


class XPServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='xp-player',
            email='xp-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.staff = get_user_model().objects.create_user(
            username='xp-staff',
            email='xp-staff@example.com',
            password='test-pass-123',
            user_type='staff',
        )
        self.action = XPAction.objects.create(
            slug='test_action',
            label='Test Action',
            xp_value=10,
            is_active=True,
        )

    def test_award_xp_increments_balance(self):
        award_xp(self.user, self.action.slug)
        balance = XPBalance.objects.get(user=self.user)
        self.assertEqual(balance.total_xp, 10)
        self.assertEqual(
            XPLedgerEntry.objects.filter(user=self.user, entry_type=XPLedgerEntry.ENTRY_EARN).count(),
            1,
        )

    def test_award_xp_is_idempotent(self):
        award_xp(self.user, self.action.slug, idempotency_key='session-1')
        award_xp(self.user, self.action.slug, idempotency_key='session-1')
        balance = XPBalance.objects.get(user=self.user)
        self.assertEqual(balance.total_xp, 10)
        self.assertEqual(
            XPLedgerEntry.objects.filter(user=self.user, idempotency_key='session-1').count(),
            1,
        )

    def test_award_xp_respects_daily_cap(self):
        self.action.max_awards_per_day = 1
        self.action.save(update_fields=['max_awards_per_day'])

        award_xp(self.user, self.action.slug)
        with self.assertRaises(DailyCapExceeded):
            award_xp(self.user, self.action.slug)

        balance = XPBalance.objects.get(user=self.user)
        self.assertEqual(balance.total_xp, 10)

    def test_award_xp_blocks_challenge_until_target_reached(self):
        source = self.action
        challenge = XPAction.objects.create(
            slug='test_challenge',
            label='Test Challenge',
            xp_value=50,
            is_active=True,
            challenge_target_count=2,
            challenge_source_action=source,
        )

        with self.assertRaises(ChallengeNotYetEligible):
            award_xp(self.user, challenge.slug)

        award_xp(self.user, source.slug, idempotency_key='r1')
        with self.assertRaises(ChallengeNotYetEligible):
            award_xp(self.user, challenge.slug)

        award_xp(self.user, source.slug, idempotency_key='r2')
        award_xp(self.user, challenge.slug)  # now eligible
        self.assertEqual(XPBalance.objects.get(user=self.user).total_xp, 20 + 50)

    def test_rank_up_cached_field_updates_and_fires_notification(self):
        big_action = XPAction.objects.create(slug='big', label='Big', xp_value=1000, is_active=True)
        award_xp(self.user, big_action.slug)

        balance = XPBalance.objects.get(user=self.user)
        self.assertEqual(balance.rank_slug, rank_for_xp(1000).slug)
        self.assertNotEqual(balance.rank_slug, RANK_THRESHOLDS[0].slug)
        self.assertTrue(Notification.objects.filter(user=self.user, title__icontains='Rank up').exists())

    def test_no_rank_up_notification_when_staying_in_same_tier(self):
        award_xp(self.user, self.action.slug)  # 10 XP, still bronze
        self.assertFalse(Notification.objects.filter(user=self.user).exists())

    def test_only_one_notification_when_skipping_multiple_tiers(self):
        huge_action = XPAction.objects.create(slug='huge', label='Huge', xp_value=20000, is_active=True)
        award_xp(self.user, huge_action.slug)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    def test_ledger_entry_records_xp_after_and_rank_after(self):
        entry = award_xp(self.user, self.action.slug)
        self.assertEqual(entry.xp_after, 10)
        self.assertEqual(entry.rank_after, rank_for_xp(10).slug)

    def test_apply_adjustment_awards_and_deducts(self):
        balance, entry = apply_adjustment(self.user, self.staff, 500, note='manual grant')
        self.assertEqual(balance.total_xp, 500)
        self.assertEqual(entry.entry_type, XPLedgerEntry.ENTRY_ADJUSTMENT)

        balance, entry = apply_adjustment(self.user, self.staff, -200)
        self.assertEqual(balance.total_xp, 300)
        self.assertEqual(entry.delta, -200)

    def test_apply_adjustment_rejects_negative_total(self):
        apply_adjustment(self.user, self.staff, 10)
        with self.assertRaises(ValueError):
            apply_adjustment(self.user, self.staff, -20)
        self.assertEqual(XPBalance.objects.get(user=self.user).total_xp, 10)

    def test_apply_adjustment_rejects_zero_delta(self):
        with self.assertRaises(ValueError):
            apply_adjustment(self.user, self.staff, 0)


class DailyProgressViewTests(TestCase):
    """
    Relies on the real seeded XPAction rows (xp/migrations/0002_seed_xp_actions.py):
    daily_login (+10 XP, no target) and daily_challenge_rounds (+30 XP,
    challenge_target_count=3, challenge_source_action=gameplay_round - the
    uncapped per-round counter, see xp migration 0004).
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='daily-progress-player',
            email='daily-progress-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_no_progress_today_returns_zeroed_checklist(self):
        response = self.client.get(reverse('xp-daily-progress'))
        self.assertEqual(response.status_code, 200)
        by_slug = {item['slug']: item for item in response.data}
        self.assertIn('daily_login', by_slug)
        self.assertIn('daily_challenge_rounds', by_slug)
        self.assertFalse(by_slug['daily_login']['completed'])
        self.assertEqual(by_slug['daily_challenge_rounds']['current_count'], 0)
        self.assertEqual(by_slug['daily_challenge_rounds']['target_count'], 3)
        self.assertFalse(by_slug['daily_challenge_rounds']['completed'])

    def test_daily_login_marked_completed_after_award(self):
        award_xp(self.user, 'daily_login', idempotency_key='today')
        response = self.client.get(reverse('xp-daily-progress'))
        by_slug = {item['slug']: item for item in response.data}
        self.assertTrue(by_slug['daily_login']['completed'])

    def test_challenge_progress_tracks_source_action_count(self):
        award_xp(self.user, 'gameplay_round', idempotency_key='round-1')
        award_xp(self.user, 'gameplay_round', idempotency_key='round-2')
        response = self.client.get(reverse('xp-daily-progress'))
        by_slug = {item['slug']: item for item in response.data}
        self.assertEqual(by_slug['daily_challenge_rounds']['current_count'], 2)
        self.assertFalse(by_slug['daily_challenge_rounds']['completed'])

    def test_challenge_marked_completed_once_awarded(self):
        for i in range(3):
            award_xp(self.user, 'gameplay_round', idempotency_key=f'round-{i}')
        award_xp(self.user, 'daily_challenge_rounds', idempotency_key='today')
        response = self.client.get(reverse('xp-daily-progress'))
        by_slug = {item['slug']: item for item in response.data}
        self.assertTrue(by_slug['daily_challenge_rounds']['completed'])
        self.assertEqual(by_slug['daily_challenge_rounds']['current_count'], 3)

    def test_current_count_never_exceeds_target_display(self):
        for i in range(6):
            award_xp(self.user, 'gameplay_round', idempotency_key=f'round-{i}')
        response = self.client.get(reverse('xp-daily-progress'))
        by_slug = {item['slug']: item for item in response.data}
        self.assertEqual(by_slug['daily_challenge_rounds']['current_count'], 3)  # clamped to target, not 6

    def test_only_checklist_actions_appear_not_qualified_gameplay_itself(self):
        response = self.client.get(reverse('xp-daily-progress'))
        slugs = {item['slug'] for item in response.data}
        self.assertEqual(slugs, {'daily_login', 'daily_challenge_rounds'})
        self.assertNotIn('qualified_gameplay', slugs)

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('xp-daily-progress'))
        self.assertEqual(response.status_code, 401)


class GlobalRankTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _make_player(self, username, total_xp):
        user = get_user_model().objects.create_user(
            username=username, email=f'{username}@example.com', password='test-pass-123', user_type='player',
        )
        XPBalance.objects.create(user=user, total_xp=total_xp)
        return user

    def test_global_rank_reflects_position_by_total_xp(self):
        leader = self._make_player('rank-leader', 500)
        middle = self._make_player('rank-middle', 200)
        last = self._make_player('rank-last', 10)

        self.client.force_authenticate(leader)
        self.assertEqual(self.client.get(reverse('xp-status')).data['global_rank'], 1)

        self.client.force_authenticate(middle)
        self.assertEqual(self.client.get(reverse('xp-status')).data['global_rank'], 2)

        self.client.force_authenticate(last)
        self.assertEqual(self.client.get(reverse('xp-status')).data['global_rank'], 3)

    def test_tied_xp_does_not_crash_and_ranks_reasonably(self):
        a = self._make_player('rank-tie-a', 100)
        self._make_player('rank-tie-b', 100)

        self.client.force_authenticate(a)
        rank = self.client.get(reverse('xp-status')).data['global_rank']
        self.assertIn(rank, (1, 2))


class AchievementsViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='achievements-player',
            email='achievements-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_all_achievements_locked_for_new_user(self):
        response = self.client.get(reverse('xp-achievements'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 4)
        self.assertTrue(all(item['unlocked'] is False for item in response.data))

    def test_streak_7day_action_unlocks_the_matching_achievement(self):
        award_xp(self.user, 'streak_7day', idempotency_key='streak-test')
        response = self.client.get(reverse('xp-achievements'))
        by_slug = {item['slug']: item for item in response.data}
        self.assertTrue(by_slug['streak_7day']['unlocked'])
        self.assertIsNotNone(by_slug['streak_7day']['earned_at'])
        self.assertFalse(by_slug['rocket_cashout_above_10x']['unlocked'])

    def test_moon_walker_and_five_alive_unlock_independently(self):
        award_xp(self.user, 'rocket_cashout_above_10x', idempotency_key='moon-walker-test')
        response = self.client.get(reverse('xp-achievements'))
        by_slug = {item['slug']: item for item in response.data}
        self.assertTrue(by_slug['rocket_cashout_above_10x']['unlocked'])
        self.assertFalse(by_slug['rocket_five_alive']['unlocked'])
        self.assertFalse(by_slug['streak_7day']['unlocked'])

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('xp-achievements'))
        self.assertEqual(response.status_code, 401)


class SubLevelTests(TestCase):
    def test_each_tier_below_the_top_has_three_contiguous_sub_ranges(self):
        for tier in RANK_THRESHOLDS[:-1]:
            ranges = sub_ranges_for_tier(tier.slug)
            self.assertEqual(len(ranges), 3)
            self.assertEqual([r['sub_level_label'] for r in ranges], ['I', 'II', 'III'])
            self.assertEqual(ranges[0]['min_xp'], tier.min_xp)
            # Contiguous, no gaps: each range starts immediately after the previous ends.
            self.assertEqual(ranges[1]['min_xp'], ranges[0]['max_xp'] + 1)
            self.assertEqual(ranges[2]['min_xp'], ranges[1]['max_xp'] + 1)
            next_tier = RANK_THRESHOLDS[RANK_THRESHOLDS.index(tier) + 1]
            self.assertEqual(ranges[2]['max_xp'], next_tier.min_xp - 1)

    def test_top_tier_has_no_sub_ranges(self):
        top = RANK_THRESHOLDS[-1]
        self.assertIsNone(sub_ranges_for_tier(top.slug))

    def test_sub_level_for_xp_matches_the_right_sub_range(self):
        bronze_ranges = sub_ranges_for_tier('bronze')
        for sub_range in bronze_ranges:
            result = sub_level_for_xp(sub_range['min_xp'])
            self.assertEqual(result['sub_level_label'], sub_range['sub_level_label'])
            self.assertEqual(result['sub_level_min_xp'], sub_range['min_xp'])
            self.assertEqual(result['sub_level_max_xp'], sub_range['max_xp'])

    def test_sub_level_for_xp_none_for_top_tier(self):
        top = RANK_THRESHOLDS[-1]
        self.assertIsNone(sub_level_for_xp(top.min_xp))
        self.assertIsNone(sub_level_for_xp(top.min_xp + 100000))

    def test_sub_level_progress_percent_is_bounded(self):
        bronze_ranges = sub_ranges_for_tier('bronze')
        first = bronze_ranges[0]
        result = sub_level_for_xp(first['min_xp'])
        self.assertEqual(result['sub_level_progress_percent'], 0)
        result = sub_level_for_xp(first['max_xp'])
        self.assertLess(result['sub_level_progress_percent'], 100)


class RankUpBonusTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='rankup-player',
            email='rankup-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.action = XPAction.objects.create(slug='rankup-test-action', label='Test', xp_value=10, is_active=True)

    def _ledger_balance(self):
        balance = PointsBalance.objects.filter(user=self.user).first()
        return balance.balance if balance else 0

    def test_no_bonus_when_staying_in_bronze(self):
        award_xp(self.user, self.action.slug)
        self.assertEqual(self._ledger_balance(), 0)
        self.assertEqual(XPBalance.objects.get(user=self.user).pending_celebration_rank, '')

    def test_rank_up_to_silver_credits_the_matching_bonus(self):
        big = XPAction.objects.create(slug='rankup-big', label='Big', xp_value=1000, is_active=True)
        award_xp(self.user, big.slug)
        self.assertEqual(self._ledger_balance(), RANK_UP_BONUS_RP['silver'])
        entry = PointsLedgerEntry.objects.get(user=self.user)
        self.assertEqual(entry.metadata.get('reason'), 'rank_up_bonus')
        self.assertEqual(entry.metadata.get('rank'), 'silver')
        self.assertEqual(XPBalance.objects.get(user=self.user).pending_celebration_rank, 'silver')

    def test_skipping_multiple_tiers_awards_only_the_final_tiers_bonus(self):
        huge = XPAction.objects.create(slug='rankup-huge', label='Huge', xp_value=20000, is_active=True)
        award_xp(self.user, huge.slug)  # bronze -> rollin_elite in one jump
        self.assertEqual(self._ledger_balance(), RANK_UP_BONUS_RP['rollin_elite'])
        self.assertEqual(PointsLedgerEntry.objects.filter(user=self.user).count(), 1)

    def test_apply_adjustment_also_credits_rank_up_bonus(self):
        staff = get_user_model().objects.create_user(
            username='rankup-staff', email='rankup-staff@example.com', password='test-pass-123', user_type='staff',
        )
        apply_adjustment(self.user, staff, 1000)
        self.assertEqual(self._ledger_balance(), RANK_UP_BONUS_RP['silver'])


class RankTiersViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='tiers-player',
            email='tiers-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        XPBalance.objects.create(user=self.user, total_xp=1500)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_returns_all_seven_tiers_with_current_and_unlocked_flags(self):
        response = self.client.get(reverse('xp-rank-tiers'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['tiers']), 7)
        self.assertEqual(response.data['caller']['total_xp'], 1500)
        self.assertEqual(response.data['caller']['rank'], 'silver')

        by_slug = {t['slug']: t for t in response.data['tiers']}
        self.assertTrue(by_slug['bronze']['is_unlocked'])
        self.assertTrue(by_slug['silver']['is_unlocked'])
        self.assertTrue(by_slug['silver']['is_current'])
        self.assertFalse(by_slug['gold']['is_unlocked'])
        self.assertFalse(by_slug['bronze']['is_current'])

    def test_rollin_legend_has_no_sub_ranges_and_no_max_xp(self):
        response = self.client.get(reverse('xp-rank-tiers'))
        legend = next(t for t in response.data['tiers'] if t['slug'] == 'rollin_legend')
        self.assertIsNone(legend['sub_ranges'])
        self.assertIsNone(legend['max_xp'])

    def test_bronze_has_no_rank_up_bonus(self):
        response = self.client.get(reverse('xp-rank-tiers'))
        bronze = next(t for t in response.data['tiers'] if t['slug'] == 'bronze')
        self.assertIsNone(bronze['rank_up_bonus_rp'])

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('xp-rank-tiers'))
        self.assertEqual(response.status_code, 401)


class AcknowledgeLevelUpViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='ack-player',
            email='ack-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.action = XPAction.objects.create(slug='ack-big', label='Big', xp_value=1000, is_active=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_status_reflects_pending_level_up_after_a_rank_up(self):
        award_xp(self.user, self.action.slug)
        response = self.client.get(reverse('xp-status'))
        self.assertEqual(response.data['pending_level_up'], {
            'rank': 'silver', 'rank_label': 'Silver', 'bonus_rp': RANK_UP_BONUS_RP['silver'],
        })

    def test_status_has_no_pending_level_up_for_a_fresh_user(self):
        response = self.client.get(reverse('xp-status'))
        self.assertIsNone(response.data['pending_level_up'])

    def test_acknowledge_clears_the_flag(self):
        award_xp(self.user, self.action.slug)
        response = self.client.post(reverse('xp-acknowledge-level-up'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['pending_level_up'])
        self.assertEqual(XPBalance.objects.get(user=self.user).pending_celebration_rank, '')

        # And it stays cleared on a subsequent status fetch.
        response = self.client.get(reverse('xp-status'))
        self.assertIsNone(response.data['pending_level_up'])

    def test_acknowledge_is_a_no_op_when_nothing_pending(self):
        response = self.client.post(reverse('xp-acknowledge-level-up'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['pending_level_up'])

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(reverse('xp-acknowledge-level-up'))
        self.assertEqual(response.status_code, 401)
