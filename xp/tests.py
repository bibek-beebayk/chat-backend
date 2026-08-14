from django.contrib.auth import get_user_model
from django.test import TestCase

from notifications.models import Notification
from .models import XPAction, XPBalance, XPLedgerEntry
from .ranks import RANK_THRESHOLDS, next_rank_for_xp, rank_for_xp
from .services import ChallengeNotYetEligible, DailyCapExceeded, apply_adjustment, award_xp


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
