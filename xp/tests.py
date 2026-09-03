from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import Notification
from .models import XPAction, XPBalance, XPLedgerEntry
from points.models import PointsBalance, PointsLedgerEntry
from .models import Tier
from .ranks import get_rank_tiers, next_rank_for_xp, rank_for_xp, sub_level_for_xp, sub_ranges_for_tier
from .services import (
    ChallengeNotYetEligible,
    DailyCapExceeded,
    apply_adjustment,
    award_matching_challenges,
    award_xp,
    rank_up_bonus_rp,
)


def _create_challenge(**kwargs):
    """
    Test helper: XPAction.objects.create() plus setting the M2M
    challenge_source_actions, which (unlike a plain FK) can't be passed to
    create() itself. Pass `challenge_source_action=<action>` or
    `challenge_source_action=[<action>, ...]` exactly as tests already did
    before the FK became an M2M - it's translated to a .set() call after
    creation. A plain XPAction.objects.create() call (no source_action
    kwarg) behaves identically either way, so this safely replaces every
    call site in this file.
    """
    sources = kwargs.pop('challenge_source_action', None)
    action = XPAction.objects.create(**kwargs)
    if sources is not None:
        action.challenge_source_actions.set(sources if isinstance(sources, (list, tuple)) else [sources])
    return action


class RankThresholdTests(TestCase):
    def setUp(self):
        # xp.ranks caches the tier ladder per process and Django's default
        # LocMem cache is not reset between tests - clear it so a test that
        # edits Tier rows can't leak a mutated ladder into another test.
        cache.clear()
        self.addCleanup(cache.clear)
    def test_rank_for_xp_at_exact_boundaries(self):
        for tier in get_rank_tiers():
            self.assertEqual(rank_for_xp(tier.min_xp).slug, tier.slug)

    def test_rank_for_xp_just_below_boundary_stays_previous_tier(self):
        tiers = get_rank_tiers()
        for previous, tier in zip(tiers, tiers[1:]):
            self.assertEqual(rank_for_xp(tier.min_xp - 1).slug, previous.slug)

    def test_rank_for_xp_zero_is_first_tier(self):
        self.assertEqual(rank_for_xp(0).slug, get_rank_tiers()[0].slug)

    def test_next_rank_for_xp_top_tier_returns_none(self):
        top = get_rank_tiers()[-1]
        self.assertIsNone(next_rank_for_xp(top.min_xp))
        self.assertIsNone(next_rank_for_xp(top.min_xp + 100000))

    def test_next_rank_for_xp_returns_the_following_tier(self):
        first, second = get_rank_tiers()[0], get_rank_tiers()[1]
        self.assertEqual(next_rank_for_xp(first.min_xp).slug, second.slug)

    def test_ladder_is_backed_by_tier_rows(self):
        self.assertEqual(Tier.objects.filter(is_active=True).count(), len(get_rank_tiers()))


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
        self.action = _create_challenge(
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
        challenge = _create_challenge(
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
        big_action = _create_challenge(slug='big', label='Big', xp_value=1000, is_active=True)
        award_xp(self.user, big_action.slug)

        balance = XPBalance.objects.get(user=self.user)
        self.assertEqual(balance.rank_slug, rank_for_xp(1000).slug)
        self.assertNotEqual(balance.rank_slug, get_rank_tiers()[0].slug)
        self.assertTrue(Notification.objects.filter(user=self.user, title__icontains='Rank up').exists())

    def test_no_rank_up_notification_when_staying_in_same_tier(self):
        award_xp(self.user, self.action.slug)  # 10 XP, still bronze
        self.assertFalse(Notification.objects.filter(user=self.user).exists())

    def test_only_one_notification_when_skipping_multiple_tiers(self):
        huge_action = _create_challenge(slug='huge', label='Huge', xp_value=20000, is_active=True)
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


class ChallengePeriodTests(TestCase):
    """
    Weekly and event challenges - the period math on XPAction
    (challenge_window/challenge_period_key/is_challenge_open) and the
    generic multi-challenge discovery in award_matching_challenges().
    Daily-period behavior is already covered end-to-end by
    XPServiceTests.test_award_xp_blocks_challenge_until_target_reached and
    DailyProgressViewTests below (both use the real seeded daily_challenge_
    rounds action), so this focuses on the two new period types.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='challenge-period-player',
            email='challenge-period-player@example.com',
            password='test-pass-123',
        )
        self.source = _create_challenge(slug='period_source', label='Source', xp_value=0, is_active=True)

    def test_weekly_challenge_only_counts_this_weeks_source_awards(self):
        challenge = _create_challenge(
            slug='weekly_test', label='Weekly Test', xp_value=50, is_active=True,
            challenge_target_count=2, challenge_source_action=self.source,
            challenge_period=XPAction.PERIOD_WEEKLY,
        )
        # An award from last week must not count toward this week's target.
        last_week = XPLedgerEntry.objects.create(
            user=self.user, entry_type=XPLedgerEntry.ENTRY_EARN, delta=0, xp_after=0,
            action=self.source, idempotency_key='old',
        )
        XPLedgerEntry.objects.filter(pk=last_week.pk).update(
            created_at=timezone.now() - timedelta(days=10),
        )
        with self.assertRaises(ChallengeNotYetEligible):
            award_xp(self.user, challenge.slug)

        award_xp(self.user, self.source.slug, idempotency_key='this-week-1')
        award_xp(self.user, self.source.slug, idempotency_key='this-week-2')
        award_xp(self.user, challenge.slug)  # now eligible
        self.assertEqual(XPBalance.objects.get(user=self.user).total_xp, 50)

    def test_weekly_challenge_period_key_changes_across_week_boundary(self):
        challenge = _create_challenge(
            slug='weekly_key_test', label='Weekly Key Test', xp_value=10, is_active=True,
            challenge_period=XPAction.PERIOD_WEEKLY,
        )
        this_week = timezone.now()
        next_week = this_week + timedelta(days=8)
        self.assertNotEqual(
            challenge.challenge_period_key(now=this_week),
            challenge.challenge_period_key(now=next_week),
        )

    def test_event_challenge_not_eligible_before_it_starts(self):
        challenge = _create_challenge(
            slug='event_future', label='Future Event', xp_value=50, is_active=True,
            challenge_target_count=1, challenge_source_action=self.source,
            challenge_period=XPAction.PERIOD_EVENT,
            event_starts_at=timezone.now() + timedelta(days=1),
            event_ends_at=timezone.now() + timedelta(days=8),
        )
        award_xp(self.user, self.source.slug, idempotency_key='r1')
        with self.assertRaises(ChallengeNotYetEligible):
            award_xp(self.user, challenge.slug)

    def test_event_challenge_not_eligible_after_it_ends(self):
        challenge = _create_challenge(
            slug='event_past', label='Past Event', xp_value=50, is_active=True,
            challenge_target_count=1, challenge_source_action=self.source,
            challenge_period=XPAction.PERIOD_EVENT,
            event_starts_at=timezone.now() - timedelta(days=8),
            event_ends_at=timezone.now() - timedelta(days=1),
        )
        award_xp(self.user, self.source.slug, idempotency_key='r1')
        with self.assertRaises(ChallengeNotYetEligible):
            award_xp(self.user, challenge.slug)

    def test_event_challenge_awardable_during_its_window(self):
        challenge = _create_challenge(
            slug='event_live', label='Live Event', xp_value=50, is_active=True,
            challenge_target_count=1, challenge_source_action=self.source,
            challenge_period=XPAction.PERIOD_EVENT,
            event_starts_at=timezone.now() - timedelta(hours=1),
            event_ends_at=timezone.now() + timedelta(days=1),
        )
        award_xp(self.user, self.source.slug, idempotency_key='r1')
        award_xp(self.user, challenge.slug)
        self.assertEqual(XPBalance.objects.get(user=self.user).total_xp, 50)

    def test_event_period_key_is_stable_for_the_life_of_the_event(self):
        # Unlike daily/weekly, an event has exactly one instance ever - its
        # key must not depend on `now` at all, since it never recurs.
        challenge = _create_challenge(
            slug='event_key_test', label='Event Key Test', xp_value=10, is_active=True,
            challenge_period=XPAction.PERIOD_EVENT,
            event_starts_at=timezone.now() - timedelta(hours=1),
            event_ends_at=timezone.now() + timedelta(days=1),
        )
        self.assertEqual(
            challenge.challenge_period_key(now=timezone.now()),
            challenge.challenge_period_key(now=timezone.now() + timedelta(hours=5)),
        )

    def test_model_validation_rejects_event_period_without_dates(self):
        from django.core.exceptions import ValidationError
        action = XPAction(slug='bad_event', label='Bad Event', xp_value=10, challenge_period=XPAction.PERIOD_EVENT)
        with self.assertRaises(ValidationError):
            action.clean()

    def test_model_validation_rejects_dates_on_non_event_period(self):
        from django.core.exceptions import ValidationError
        action = XPAction(
            slug='bad_daily', label='Bad Daily', xp_value=10, challenge_period=XPAction.PERIOD_DAILY,
            event_starts_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            action.clean()

    def test_award_matching_challenges_attempts_every_challenge_on_the_source(self):
        """
        The mechanism that makes "add a new challenge from admin alone"
        actually true: a game calls this once after firing its counter
        action, and every currently configured challenge sourced on it -
        daily, weekly, or event - is attempted, with no code naming any
        specific challenge slug.
        """
        daily = _create_challenge(
            slug='matching_daily', label='Matching Daily', xp_value=5, is_active=True,
            challenge_target_count=1, challenge_source_action=self.source,
            challenge_period=XPAction.PERIOD_DAILY,
        )
        weekly = _create_challenge(
            slug='matching_weekly', label='Matching Weekly', xp_value=7, is_active=True,
            challenge_target_count=1, challenge_source_action=self.source,
            challenge_period=XPAction.PERIOD_WEEKLY,
        )
        # A challenge sourced on something else entirely must not be touched.
        other_source = _create_challenge(slug='other_source', label='Other', xp_value=0, is_active=True)
        unrelated = _create_challenge(
            slug='matching_unrelated', label='Unrelated', xp_value=100, is_active=True,
            challenge_target_count=1, challenge_source_action=other_source,
        )

        award_xp(self.user, self.source.slug, idempotency_key='r1')
        award_matching_challenges(self.user, source_action_slug=self.source.slug)

        self.assertTrue(XPLedgerEntry.objects.filter(user=self.user, action=daily).exists())
        self.assertTrue(XPLedgerEntry.objects.filter(user=self.user, action=weekly).exists())
        self.assertFalse(XPLedgerEntry.objects.filter(user=self.user, action=unrelated).exists())

    def test_award_matching_challenges_is_a_silent_noop_with_no_configured_challenges(self):
        # Must never raise just because nothing happens to be configured -
        # every game calls this unconditionally after every round.
        award_matching_challenges(self.user, source_action_slug=self.source.slug)

    def test_award_matching_challenges_one_ineligible_challenge_does_not_block_another(self):
        eligible = _create_challenge(
            slug='matching_eligible', label='Eligible', xp_value=5, is_active=True,
            challenge_target_count=1, challenge_source_action=self.source,
        )
        needs_more = _create_challenge(
            slug='matching_needs_more', label='Needs More', xp_value=5, is_active=True,
            challenge_target_count=5, challenge_source_action=self.source,
        )
        award_xp(self.user, self.source.slug, idempotency_key='r1')
        award_matching_challenges(self.user, source_action_slug=self.source.slug)

        self.assertTrue(XPLedgerEntry.objects.filter(user=self.user, action=eligible).exists())
        self.assertFalse(XPLedgerEntry.objects.filter(user=self.user, action=needs_more).exists())

    def test_multi_game_challenge_sums_progress_across_all_listed_sources(self):
        """
        The actual "add as many games as I like" mechanism: a challenge
        lists more than one source action, and progress is the combined
        count across all of them - a round from either game advances it.
        """
        game_a = _create_challenge(slug='game_a_rounds', label='Game A Rounds', xp_value=0, is_active=True)
        game_b = _create_challenge(slug='game_b_rounds', label='Game B Rounds', xp_value=0, is_active=True)
        challenge = _create_challenge(
            slug='two_game_challenge', label='Two Game Challenge', xp_value=50, is_active=True,
            challenge_target_count=3, challenge_source_action=[game_a, game_b],
        )

        award_xp(self.user, game_a.slug, idempotency_key='a1')
        award_xp(self.user, game_b.slug, idempotency_key='b1')
        with self.assertRaises(ChallengeNotYetEligible):
            award_xp(self.user, challenge.slug)

        award_xp(self.user, game_a.slug, idempotency_key='a2')
        award_xp(self.user, challenge.slug)  # 3rd combined round makes it eligible
        self.assertEqual(XPBalance.objects.get(user=self.user).total_xp, 50)

    def test_a_challenge_scoped_to_one_game_ignores_rounds_from_another(self):
        game_a = _create_challenge(slug='scoped_game_a', label='Game A', xp_value=0, is_active=True)
        game_b = _create_challenge(slug='scoped_game_b', label='Game B', xp_value=0, is_active=True)
        challenge = _create_challenge(
            slug='scoped_to_a', label='Scoped To A', xp_value=50, is_active=True,
            challenge_target_count=1, challenge_source_action=game_a,
        )

        # A round in game_b must not count toward a challenge scoped to game_a.
        award_xp(self.user, game_b.slug, idempotency_key='b1')
        with self.assertRaises(ChallengeNotYetEligible):
            award_xp(self.user, challenge.slug)

        award_xp(self.user, game_a.slug, idempotency_key='a1')
        award_xp(self.user, challenge.slug)
        self.assertEqual(XPBalance.objects.get(user=self.user).total_xp, 50)

    def test_award_matching_challenges_reaches_a_challenge_via_any_of_its_sources(self):
        """
        A multi-game challenge must be discovered (and attempted) when
        EITHER game fires its round - not only when the first-listed
        source does - since award_matching_challenges is called
        independently by each game after its own counter fires.
        """
        game_a = _create_challenge(slug='discover_game_a', label='Game A', xp_value=0, is_active=True)
        game_b = _create_challenge(slug='discover_game_b', label='Game B', xp_value=0, is_active=True)
        challenge = _create_challenge(
            slug='discoverable_both', label='Discoverable', xp_value=10, is_active=True,
            challenge_target_count=1, challenge_source_action=[game_a, game_b],
        )

        award_xp(self.user, game_b.slug, idempotency_key='b1')
        # Only game_b fired - a call scoped to game_a's slug must still find
        # and attempt this challenge, since it lists both as sources.
        award_matching_challenges(self.user, source_action_slug=game_b.slug)

        self.assertTrue(XPLedgerEntry.objects.filter(user=self.user, action=challenge).exists())


class RotationTests(TestCase):
    """
    Daily and Weekly challenge rotation - the pure selection function
    (current_rotation_pool_ids), the model-level plumbing that calls it
    (XPAction.is_in_current_rotation / is_challenge_open), and the
    RotationConfig singleton that controls how many of each are live.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='rotation-player', email='rotation-player@example.com', password='test-pass-123',
        )

    # --- the pure function - no DB, no model instances ---

    def test_selection_is_deterministic_for_the_same_pool_and_period(self):
        from .models import current_rotation_pool_ids
        pool = [(1, 'a'), (2, 'b'), (3, 'c'), (4, 'd'), (5, 'e')]
        first = current_rotation_pool_ids(pool, count=2, period_key='2026-09-04')
        second = current_rotation_pool_ids(pool, count=2, period_key='2026-09-04')
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)

    def test_selection_changes_on_a_different_period(self):
        from .models import current_rotation_pool_ids
        pool = [(1, 'a'), (2, 'b'), (3, 'c'), (4, 'd'), (5, 'e')]
        this_period = current_rotation_pool_ids(pool, count=2, period_key='2026-09-04')
        next_period = current_rotation_pool_ids(pool, count=2, period_key='2026-09-05')
        # Not a hard guarantee for every possible pool (a 2-of-5 draw could
        # coincidentally repeat), but true for this fixed pool/keys pair -
        # pinned here as a concrete demonstration that the period key
        # genuinely changes the outcome, not just a same-every-time constant.
        self.assertNotEqual(this_period, next_period)

    def test_count_at_or_above_pool_size_returns_the_whole_pool(self):
        from .models import current_rotation_pool_ids
        pool = [(1, 'a'), (2, 'b'), (3, 'c')]
        self.assertEqual(current_rotation_pool_ids(pool, count=10, period_key='2026-09-04'), {1, 2, 3})

    def test_zero_count_selects_nothing(self):
        from .models import current_rotation_pool_ids
        pool = [(1, 'a'), (2, 'b'), (3, 'c')]
        self.assertEqual(current_rotation_pool_ids(pool, count=0, period_key='2026-09-04'), set())

    def test_empty_pool_is_safe(self):
        from .models import current_rotation_pool_ids
        self.assertEqual(current_rotation_pool_ids([], count=3, period_key='2026-09-04'), set())

    # --- the model/DB layer ---

    def test_non_pool_challenge_is_always_in_rotation(self):
        action = _create_challenge(slug='rotation_not_pooled', label='Not Pooled', xp_value=5, is_active=True)
        self.assertTrue(action.is_in_current_rotation())

    def test_exactly_daily_active_count_of_the_daily_pool_is_selected(self):
        from challenges.models import RotationConfig
        RotationConfig.objects.update_or_create(pk=1, defaults={'daily_active_count': 2})

        pool = [
            _create_challenge(
                slug=f'rotation_pool_{i}', label=f'Pool {i}', xp_value=5, is_active=True,
                rotation_pool=True, challenge_period=XPAction.PERIOD_DAILY,
            )
            for i in range(5)
        ]
        live = [a for a in pool if a.is_in_current_rotation()]
        self.assertEqual(len(live), 2)

    def test_exactly_weekly_active_count_of_the_weekly_pool_is_selected(self):
        from challenges.models import RotationConfig
        RotationConfig.objects.update_or_create(pk=1, defaults={'weekly_active_count': 1})

        pool = [
            _create_challenge(
                slug=f'weekly_rotation_pool_{i}', label=f'Weekly Pool {i}', xp_value=5, is_active=True,
                rotation_pool=True, challenge_period=XPAction.PERIOD_WEEKLY,
            )
            for i in range(4)
        ]
        live = [a for a in pool if a.is_in_current_rotation()]
        self.assertEqual(len(live), 1)

    def test_daily_and_weekly_pools_never_compete_for_the_same_slots(self):
        """
        A Daily pool challenge and a Weekly pool challenge must be ranked
        and selected entirely independently - one's count and rotation
        must never be influenced by the other's pool membership.
        """
        from challenges.models import RotationConfig
        RotationConfig.objects.update_or_create(pk=1, defaults={'daily_active_count': 5, 'weekly_active_count': 5})

        daily_pool = [
            _create_challenge(
                slug=f'isolation_daily_{i}', label=f'Daily {i}', xp_value=5, is_active=True,
                rotation_pool=True, challenge_period=XPAction.PERIOD_DAILY,
            )
            for i in range(2)
        ]
        weekly_pool = [
            _create_challenge(
                slug=f'isolation_weekly_{i}', label=f'Weekly {i}', xp_value=5, is_active=True,
                rotation_pool=True, challenge_period=XPAction.PERIOD_WEEKLY,
            )
            for i in range(2)
        ]
        # Counts of 5 exceed both 2-item pools, so with correct isolation
        # every challenge in both pools is live - if the pools were ever
        # merged into one ranking, this would still pass by coincidence, so
        # the real assertion is the reverse: shrink each count to less than
        # its own pool and confirm the OTHER pool is unaffected.
        for a in daily_pool + weekly_pool:
            self.assertTrue(a.is_in_current_rotation())

        RotationConfig.objects.update_or_create(pk=1, defaults={'daily_active_count': 0, 'weekly_active_count': 5})
        self.assertTrue(all(not a.is_in_current_rotation() for a in daily_pool))
        self.assertTrue(all(a.is_in_current_rotation() for a in weekly_pool))

    def test_rotation_selection_is_stable_within_the_same_period(self):
        from challenges.models import RotationConfig
        RotationConfig.objects.update_or_create(pk=1, defaults={'daily_active_count': 2})

        pool = [
            _create_challenge(
                slug=f'rotation_stable_{i}', label=f'Pool {i}', xp_value=5, is_active=True,
                rotation_pool=True, challenge_period=XPAction.PERIOD_DAILY,
            )
            for i in range(4)
        ]
        first_pass = {a.slug for a in pool if a.is_in_current_rotation()}
        second_pass = {a.slug for a in pool if a.is_in_current_rotation()}
        self.assertEqual(first_pass, second_pass)

    def test_a_dormant_pool_challenge_cannot_be_earned_even_if_the_target_is_met(self):
        """
        Rotation must gate eligibility, not just display - a challenge left
        out of the current rotation must not be quietly earnable in the
        background while merely hidden from the checklist.
        """
        from challenges.models import RotationConfig
        RotationConfig.objects.update_or_create(pk=1, defaults={'daily_active_count': 0})  # nothing live

        source = _create_challenge(slug='rotation_dormant_source', label='Source', xp_value=0, is_active=True)
        challenge = _create_challenge(
            slug='rotation_dormant_challenge', label='Dormant', xp_value=5, is_active=True,
            challenge_target_count=1, challenge_source_action=source,
            rotation_pool=True, challenge_period=XPAction.PERIOD_DAILY,
        )
        award_xp(self.user, source.slug, idempotency_key='r1')

        with self.assertRaises(ChallengeNotYetEligible):
            award_xp(self.user, challenge.slug)

    def test_model_validation_accepts_rotation_pool_on_daily_and_weekly(self):
        for period in (XPAction.PERIOD_DAILY, XPAction.PERIOD_WEEKLY):
            action = XPAction(slug=f'rotation_ok_{period}', label='OK', xp_value=5, challenge_period=period, rotation_pool=True)
            action.clean()  # must not raise

    def test_model_validation_rejects_rotation_pool_on_an_event_challenge(self):
        from django.core.exceptions import ValidationError
        action = XPAction(
            slug='rotation_bad_period', label='Bad', xp_value=5,
            challenge_period=XPAction.PERIOD_EVENT, rotation_pool=True,
            event_starts_at=timezone.now(), event_ends_at=timezone.now() + timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            action.clean()

    def test_get_solo_is_a_true_singleton(self):
        from challenges.models import RotationConfig
        first = RotationConfig.get_solo()
        second = RotationConfig.get_solo()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(RotationConfig.objects.count(), 1)


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

    def test_daily_challenge_reports_its_period_and_a_reset_time(self):
        response = self.client.get(reverse('xp-daily-progress'))
        by_slug = {item['slug']: item for item in response.data}
        self.assertEqual(by_slug['daily_challenge_rounds']['challenge_period'], 'daily')
        self.assertIsNotNone(by_slug['daily_challenge_rounds']['resets_at'])

    def test_weekly_challenge_appears_with_its_period(self):
        _create_challenge(
            slug='weekly_checklist_test', label='Weekly Checklist Test', xp_value=20, is_active=True,
            is_daily_checklist=True, challenge_period=XPAction.PERIOD_WEEKLY,
        )
        response = self.client.get(reverse('xp-daily-progress'))
        by_slug = {item['slug']: item for item in response.data}
        self.assertIn('weekly_checklist_test', by_slug)
        self.assertEqual(by_slug['weekly_checklist_test']['challenge_period'], 'weekly')

    def test_event_challenge_is_hidden_before_its_window_opens(self):
        _create_challenge(
            slug='event_checklist_future', label='Future Event Checklist', xp_value=20, is_active=True,
            is_daily_checklist=True, challenge_target_count=1,
            challenge_source_action=XPAction.objects.get(slug='gameplay_round'),
            challenge_period=XPAction.PERIOD_EVENT,
            event_starts_at=timezone.now() + timedelta(days=1),
            event_ends_at=timezone.now() + timedelta(days=8),
        )
        response = self.client.get(reverse('xp-daily-progress'))
        slugs = {item['slug'] for item in response.data}
        self.assertNotIn('event_checklist_future', slugs)

    def test_event_challenge_is_visible_during_its_window(self):
        _create_challenge(
            slug='event_checklist_live', label='Live Event Checklist', xp_value=20, is_active=True,
            is_daily_checklist=True, challenge_target_count=1,
            challenge_source_action=XPAction.objects.get(slug='gameplay_round'),
            challenge_period=XPAction.PERIOD_EVENT,
            event_starts_at=timezone.now() - timedelta(hours=1),
            event_ends_at=timezone.now() + timedelta(days=1),
        )
        response = self.client.get(reverse('xp-daily-progress'))
        by_slug = {item['slug']: item for item in response.data}
        self.assertIn('event_checklist_live', by_slug)
        self.assertEqual(by_slug['event_checklist_live']['challenge_period'], 'event')

    def test_event_challenge_is_hidden_after_its_window_closes(self):
        _create_challenge(
            slug='event_checklist_past', label='Past Event Checklist', xp_value=20, is_active=True,
            is_daily_checklist=True, challenge_target_count=1,
            challenge_source_action=XPAction.objects.get(slug='gameplay_round'),
            challenge_period=XPAction.PERIOD_EVENT,
            event_starts_at=timezone.now() - timedelta(days=8),
            event_ends_at=timezone.now() - timedelta(days=1),
        )
        response = self.client.get(reverse('xp-daily-progress'))
        slugs = {item['slug'] for item in response.data}
        self.assertNotIn('event_checklist_past', slugs)

    def test_only_todays_rotation_pool_challenges_appear_on_the_checklist(self):
        from challenges.models import RotationConfig
        RotationConfig.objects.update_or_create(pk=1, defaults={'daily_active_count': 2})

        pool = [
            XPAction.objects.create(
                slug=f'checklist_rotation_{i}', label=f'Pool {i}', xp_value=5, is_active=True,
                is_daily_checklist=True, challenge_target_count=1,
                challenge_period=XPAction.PERIOD_DAILY, rotation_pool=True,
            )
            for i in range(5)
        ]
        for action in pool:
            action.challenge_source_actions.set([XPAction.objects.get(slug='gameplay_round')])

        response = self.client.get(reverse('xp-daily-progress'))
        pool_slugs_shown = {item['slug'] for item in response.data} & {a.slug for a in pool}
        self.assertEqual(len(pool_slugs_shown), 2)


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
        # Length is derived from the flagged rows rather than hardcoded, so
        # enabling another achievement in admin doesn't break this test for
        # an unrelated reason.
        expected = XPAction.objects.filter(is_achievement=True, is_active=True).count()

        response = self.client.get(reverse('xp-achievements'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), expected)
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
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_each_tier_below_the_top_has_three_contiguous_sub_ranges(self):
        tiers = get_rank_tiers()
        for tier in tiers[:-1]:
            ranges = sub_ranges_for_tier(tier.slug)
            self.assertEqual(len(ranges), 3)
            self.assertEqual([r['sub_level_label'] for r in ranges], ['I', 'II', 'III'])
            self.assertEqual(ranges[0]['min_xp'], tier.min_xp)
            # Contiguous, no gaps: each range starts immediately after the previous ends.
            self.assertEqual(ranges[1]['min_xp'], ranges[0]['max_xp'] + 1)
            self.assertEqual(ranges[2]['min_xp'], ranges[1]['max_xp'] + 1)
            next_tier = tiers[tiers.index(tier) + 1]
            self.assertEqual(ranges[2]['max_xp'], next_tier.min_xp - 1)

    def test_top_tier_has_no_sub_ranges(self):
        top = get_rank_tiers()[-1]
        self.assertIsNone(sub_ranges_for_tier(top.slug))

    def test_sub_level_for_xp_matches_the_right_sub_range(self):
        bronze_ranges = sub_ranges_for_tier('bronze')
        for sub_range in bronze_ranges:
            result = sub_level_for_xp(sub_range['min_xp'])
            self.assertEqual(result['sub_level_label'], sub_range['sub_level_label'])
            self.assertEqual(result['sub_level_min_xp'], sub_range['min_xp'])
            self.assertEqual(result['sub_level_max_xp'], sub_range['max_xp'])

    def test_sub_level_for_xp_none_for_top_tier(self):
        top = get_rank_tiers()[-1]
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
        self.action = _create_challenge(slug='rankup-test-action', label='Test', xp_value=10, is_active=True)

    def _ledger_balance(self):
        balance = PointsBalance.objects.filter(user=self.user).first()
        return balance.balance if balance else 0

    def test_no_bonus_when_staying_in_bronze(self):
        award_xp(self.user, self.action.slug)
        self.assertEqual(self._ledger_balance(), 0)
        self.assertEqual(XPBalance.objects.get(user=self.user).pending_celebration_rank, '')

    def test_rank_up_to_silver_credits_the_matching_bonus(self):
        big = _create_challenge(slug='rankup-big', label='Big', xp_value=1000, is_active=True)
        award_xp(self.user, big.slug)
        self.assertEqual(self._ledger_balance(), rank_up_bonus_rp('silver'))
        entry = PointsLedgerEntry.objects.get(user=self.user)
        self.assertEqual(entry.metadata.get('reason'), 'rank_up_bonus')
        self.assertEqual(entry.metadata.get('rank'), 'silver')
        self.assertEqual(XPBalance.objects.get(user=self.user).pending_celebration_rank, 'silver')

    def test_skipping_multiple_tiers_awards_only_the_final_tiers_bonus(self):
        huge = _create_challenge(slug='rankup-huge', label='Huge', xp_value=20000, is_active=True)
        award_xp(self.user, huge.slug)  # bronze -> rollin_elite in one jump
        self.assertEqual(self._ledger_balance(), rank_up_bonus_rp('rollin_elite'))
        self.assertEqual(PointsLedgerEntry.objects.filter(user=self.user).count(), 1)

    def test_apply_adjustment_also_credits_rank_up_bonus(self):
        staff = get_user_model().objects.create_user(
            username='rankup-staff', email='rankup-staff@example.com', password='test-pass-123', user_type='staff',
        )
        apply_adjustment(self.user, staff, 1000)
        self.assertEqual(self._ledger_balance(), rank_up_bonus_rp('silver'))


class RankTiersViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
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

    def test_tiers_expose_a_badge_url_field_backed_by_the_model(self):
        response = self.client.get(reverse('xp-rank-tiers'))
        for tier in response.data['tiers']:
            self.assertIn('badge_url', tier)
            self.assertIsNone(tier['badge_url'])  # no artwork uploaded in tests

    def test_editing_a_tier_row_changes_the_ladder(self):
        Tier.objects.filter(slug='silver').update(min_xp=1200, name='Sterling')
        from .ranks import invalidate_tier_cache
        invalidate_tier_cache()
        response = self.client.get(reverse('xp-rank-tiers'))
        by_slug = {t['slug']: t for t in response.data['tiers']}
        self.assertEqual(by_slug['silver']['label'], 'Sterling')
        self.assertEqual(by_slug['silver']['min_xp'], 1200)
        self.assertEqual(by_slug['bronze']['max_xp'], 1199)
        self.assertEqual(response.data['caller']['rank'], 'silver')  # 1500 XP still silver

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
        self.action = _create_challenge(slug='ack-big', label='Big', xp_value=1000, is_active=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_status_reflects_pending_level_up_after_a_rank_up(self):
        award_xp(self.user, self.action.slug)
        response = self.client.get(reverse('xp-status'))
        self.assertEqual(response.data['pending_level_up'], {
            'rank': 'silver', 'rank_label': 'Silver', 'bonus_rp': rank_up_bonus_rp('silver'),
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
