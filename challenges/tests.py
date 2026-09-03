from django.contrib.auth import get_user_model
from django.test import TestCase

from xp.models import XPAction
from .admin import DailyChallengeForm, SpecialChallengeForm, WeeklyChallengeForm
from .models import DailyChallenge, SpecialChallenge, WeeklyChallenge


class ChallengeProxyManagerTests(TestCase):
    """
    Each proxy model's manager is what scopes the admin list to just that
    period - and, just as important, excludes non-challenge XPAction rows
    (achievements, background counters like gameplay_round) that share the
    same table but have no target set.
    """

    def test_managers_scope_by_period_and_require_a_target(self):
        daily = XPAction.objects.create(
            slug='proxy_test_daily', label='Daily', xp_value=5, is_active=True,
            challenge_target_count=1, challenge_period=XPAction.PERIOD_DAILY,
        )
        weekly = XPAction.objects.create(
            slug='proxy_test_weekly', label='Weekly', xp_value=5, is_active=True,
            challenge_target_count=1, challenge_period=XPAction.PERIOD_WEEKLY,
        )
        # A background counter (no target set) must not appear in any of
        # the three, even though its period defaults to 'daily'.
        XPAction.objects.create(slug='proxy_test_counter', label='Counter', xp_value=0, is_active=True)
        # A non-challenge daily action (e.g. daily_login-shaped) likewise.
        XPAction.objects.create(
            slug='proxy_test_simple_daily', label='Simple Daily', xp_value=5, is_active=True,
            is_daily_checklist=True,
        )

        daily_slugs = set(DailyChallenge.objects.values_list('slug', flat=True))
        weekly_slugs = set(WeeklyChallenge.objects.values_list('slug', flat=True))
        self.assertIn('proxy_test_daily', daily_slugs)
        self.assertNotIn('proxy_test_weekly', daily_slugs)
        self.assertNotIn('proxy_test_counter', daily_slugs)
        self.assertNotIn('proxy_test_simple_daily', daily_slugs)
        self.assertIn('proxy_test_weekly', weekly_slugs)
        self.assertNotIn('proxy_test_daily', weekly_slugs)

    def test_a_proxy_model_row_is_editable_as_a_real_xpaction(self):
        # Proxy models share the underlying table - editing through one
        # must be visible through the others / the base model immediately.
        challenge = DailyChallenge.objects.create(
            slug='proxy_edit_test', label='Edit Test', xp_value=5, is_active=True,
            challenge_target_count=1, challenge_period=XPAction.PERIOD_DAILY,
        )
        XPAction.objects.filter(pk=challenge.pk).update(xp_value=99)
        challenge.refresh_from_db()
        self.assertEqual(challenge.xp_value, 99)


class ChallengeFormTests(TestCase):
    """
    The forms behind the three admin pages - specifically that each locks
    challenge_period BEFORE model validation runs (not merely on save),
    since XPAction.clean() checks event dates against the period and would
    reject a valid Special Challenge submission if that ordering were
    wrong. See challenges/admin.py::_ChallengeFormBase's docstring.
    """

    def setUp(self):
        self.source = XPAction.objects.create(slug='form_test_source', label='Source', xp_value=0, is_active=True)

    def _base_data(self, slug):
        return {
            'slug': slug,
            'label': 'Test Challenge',
            'description': '',
            'xp_value': '10',
            'is_active': 'on',
            'challenge_target_count': '3',
            'challenge_source_actions': [self.source.pk],
            'is_daily_checklist': 'on',
            'display_order': '10',
            'action_url': '',
            'icon': '',
        }

    def test_target_and_source_are_required_even_though_the_model_allows_blank(self):
        # XPAction itself allows a blank target/source (shared with plain
        # rows like daily_login via the general XP Actions admin) - these
        # forms tighten that, since a challenge saved without either can
        # never resolve or be discovered by award_matching_challenges.
        data = self._base_data('form_test_missing_target')
        data['challenge_target_count'] = ''
        data['challenge_source_actions'] = []
        form = DailyChallengeForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('challenge_target_count', form.errors)
        self.assertIn('challenge_source_actions', form.errors)

    def test_daily_form_saves_with_the_daily_period_and_no_event_dates(self):
        form = DailyChallengeForm(data=self._base_data('form_test_daily'))
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save()
        self.assertEqual(obj.challenge_period, XPAction.PERIOD_DAILY)
        self.assertIsNone(obj.event_starts_at)
        self.assertIsNone(obj.event_ends_at)

    def test_weekly_form_saves_with_the_weekly_period(self):
        form = WeeklyChallengeForm(data=self._base_data('form_test_weekly'))
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save()
        self.assertEqual(obj.challenge_period, XPAction.PERIOD_WEEKLY)

    def test_special_form_requires_both_event_dates(self):
        form = SpecialChallengeForm(data=self._base_data('form_test_special_missing_dates'))
        self.assertFalse(form.is_valid())

    def test_special_form_saves_with_the_event_period_when_dates_are_given(self):
        from django.utils import timezone
        from datetime import timedelta

        data = self._base_data('form_test_special')
        data['event_starts_at'] = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        data['event_ends_at'] = (timezone.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        form = SpecialChallengeForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save()
        self.assertEqual(obj.challenge_period, XPAction.PERIOD_EVENT)
        self.assertIsNotNone(obj.event_starts_at)
        self.assertIsNotNone(obj.event_ends_at)

    def test_new_challenge_defaults_to_shown_on_the_checklist(self):
        # The model's own default is False (shared with background actions
        # that must stay hidden) - these forms override that default for a
        # brand-new challenge, since anything created here is meant to be
        # player-visible unless staff explicitly unticks it.
        form = DailyChallengeForm()
        self.assertTrue(form.initial.get('is_daily_checklist'))


class ChallengeAdminSiteTests(TestCase):
    """The actual admin views, end to end, as staff would use them."""

    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            username='challenge-admin', email='challenge-admin@example.com', password='test-pass-123',
        )
        self.client.force_login(self.staff)

    def test_all_three_challenge_admins_are_registered_and_reachable(self):
        for path in ('challenges/dailychallenge', 'challenges/weeklychallenge', 'challenges/specialchallenge'):
            response = self.client.get(f'/admin/{path}/')
            self.assertEqual(response.status_code, 200, path)

    def test_creating_a_weekly_challenge_through_the_admin_form(self):
        source = XPAction.objects.create(slug='admin_weekly_test_source', label='Source', xp_value=0, is_active=True)
        response = self.client.post('/admin/challenges/weeklychallenge/add/', data={
            'slug': 'admin_weekly_test',
            'label': 'Admin Weekly Test',
            'description': '',
            'xp_value': '15',
            'is_active': 'on',
            'challenge_target_count': '10',
            'challenge_source_actions': [source.pk],
            'is_daily_checklist': 'on',
            'display_order': '10',
            'action_url': '',
            'icon': '',
        })
        self.assertEqual(response.status_code, 302)  # redirect on success
        created = XPAction.objects.get(slug='admin_weekly_test')
        self.assertEqual(created.challenge_period, XPAction.PERIOD_WEEKLY)
        self.assertEqual(created.challenge_target_count, 10)
        self.assertEqual(list(created.challenge_source_actions.values_list('slug', flat=True)), ['admin_weekly_test_source'])

    def test_a_weekly_challenge_does_not_appear_in_the_daily_admin_list(self):
        WeeklyChallenge.objects.create(
            slug='admin_weekly_visibility_test', label='W', xp_value=1, is_active=True,
            challenge_target_count=1, challenge_period=XPAction.PERIOD_WEEKLY,
        )
        response = self.client.get('/admin/challenges/dailychallenge/')
        self.assertNotContains(response, 'admin_weekly_visibility_test')
