from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from points.models import PointAction, PointsBalance, PointsLedgerEntry
from xp.models import XPAction, XPBalance, XPLedgerEntry
from .services import grant_daily_login_rewards, grant_registration_rewards


class GrantRegistrationRewardsTests(TestCase):
    """
    These rely on the seed migrations (points.0006_seed_redemption_config_and_actions,
    xp.0002_seed_xp_actions) having already created the 'registration_bonus'
    / 'registration' action rows - exactly the state a real deploy is in.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='reg-player',
            email='reg-player@example.com',
            password='test-pass-123',
            user_type='player',
        )

    def test_grants_both_rp_and_xp(self):
        grant_registration_rewards(self.user)

        rp_balance = PointsBalance.objects.get(user=self.user)
        xp_balance = XPBalance.objects.get(user=self.user)
        self.assertEqual(rp_balance.balance, 1000)
        self.assertEqual(xp_balance.total_xp, 10)

    def test_is_idempotent_across_repeated_calls(self):
        grant_registration_rewards(self.user)
        grant_registration_rewards(self.user)

        self.assertEqual(PointsBalance.objects.get(user=self.user).balance, 1000)
        self.assertEqual(XPBalance.objects.get(user=self.user).total_xp, 10)
        self.assertEqual(
            PointsLedgerEntry.objects.filter(user=self.user, idempotency_key=f'registration:{self.user.id}').count(),
            1,
        )
        self.assertEqual(
            XPLedgerEntry.objects.filter(user=self.user, idempotency_key=f'registration:{self.user.id}').count(),
            1,
        )

    def test_misconfigured_xp_action_rolls_back_the_rp_award_too(self):
        # Prove the RP+XP pair is genuinely atomic: if XP fails, RP must not
        # have landed either, even though award_points() is called first.
        XPAction.objects.filter(slug='registration').update(is_active=False)

        with self.assertRaises(XPAction.DoesNotExist):
            grant_registration_rewards(self.user)

        self.assertFalse(PointsBalance.objects.filter(user=self.user).exists())
        self.assertFalse(XPBalance.objects.filter(user=self.user).exists())
        self.assertEqual(PointsLedgerEntry.objects.filter(user=self.user).count(), 0)


class GrantDailyLoginRewardsTests(TestCase):
    def setUp(self):
        self.player = get_user_model().objects.create_user(
            username='login-player',
            email='login-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.staff = get_user_model().objects.create_user(
            username='login-staff',
            email='login-staff@example.com',
            password='test-pass-123',
            user_type='staff',
        )

    def test_awards_xp_once_per_day(self):
        grant_daily_login_rewards(self.player)
        grant_daily_login_rewards(self.player)

        self.assertEqual(XPBalance.objects.get(user=self.player).total_xp, 10)
        key = f'daily_login:{self.player.id}:{timezone.localdate().isoformat()}'
        self.assertEqual(XPLedgerEntry.objects.filter(user=self.player, idempotency_key=key).count(), 1)

    def test_does_not_award_rp(self):
        # Doc's RP-earning-activity list doesn't include daily login -
        # XP-only, must not touch the points balance at all.
        grant_daily_login_rewards(self.player)
        self.assertFalse(PointsBalance.objects.filter(user=self.player).exists())

    def test_staff_and_agent_never_get_daily_login_xp(self):
        grant_daily_login_rewards(self.staff)
        self.assertFalse(XPBalance.objects.filter(user=self.staff).exists())

    def test_swallows_misconfiguration_without_raising(self):
        XPAction.objects.filter(slug='daily_login').update(is_active=False)
        grant_daily_login_rewards(self.player)  # must not raise
        self.assertFalse(XPBalance.objects.filter(user=self.player).exists())


class LoginHardeningTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.core.management import call_command
        call_command('createcachetable', verbosity=0)

    def setUp(self):
        from django.core.cache import cache
        from rest_framework.test import APIClient

        cache.clear()
        self.client = APIClient()
        self.login_url = '/api/auth/login/'
        self.resend_otp_url = '/api/auth/resend-otp/'

        self.active_user = get_user_model().objects.create_user(
            username='active_player',
            email='active@example.com',
            password='RightPassword123!',
            user_type='player',
            is_active=True,
        )
        self.unverified_user = get_user_model().objects.create_user(
            username='unverified_player',
            email='unverified@example.com',
            password='RightPassword123!',
            user_type='player',
            is_active=False,
        )

    def test_wrong_password_returns_401_invalid_credentials(self):
        response = self.client.post(
            self.login_url,
            {'username': 'active_player', 'password': 'WrongPassword!'},
            format='json',
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {
                'status': 'error',
                'code': 'invalid_credentials',
                'message': 'Incorrect username, email or password. Please try again.',
                'errors': None,
            },
        )

    def test_unknown_user_returns_identical_401_body(self):
        wrong_pw_resp = self.client.post(
            self.login_url,
            {'username': 'active_player', 'password': 'WrongPassword!'},
            format='json',
        )
        unknown_resp = self.client.post(
            self.login_url,
            {'username': 'does_not_exist_user', 'password': 'WrongPassword!'},
            format='json',
        )
        self.assertEqual(unknown_resp.status_code, 401)
        self.assertEqual(unknown_resp.json(), wrong_pw_resp.json())

    def test_unverified_user_with_right_password_returns_403_email_not_verified(self):
        response = self.client.post(
            self.login_url,
            {'username': 'unverified_player', 'password': 'RightPassword123!'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {
                'status': 'error',
                'code': 'email_not_verified',
                'message': "Your email isn't verified yet. Enter the code we sent to finish signing up.",
                'errors': {'email': 'unverified@example.com'},
            },
        )

    def test_unverified_user_with_wrong_password_returns_generic_401(self):
        response = self.client.post(
            self.login_url,
            {'username': 'unverified@example.com', 'password': 'WrongPassword!'},
            format='json',
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {
                'status': 'error',
                'code': 'invalid_credentials',
                'message': 'Incorrect username, email or password. Please try again.',
                'errors': None,
            },
        )

    def test_sixth_attempt_for_same_identifier_returns_429_with_retry_after(self):
        for _ in range(5):
            resp = self.client.post(
                self.login_url,
                {'username': 'active_player', 'password': 'WrongPassword!'},
                format='json',
            )
            self.assertEqual(resp.status_code, 401)

        throttled = self.client.post(
            self.login_url,
            {'username': '  ACTIVE_PLAYER  ', 'password': 'WrongPassword!'},
            format='json',
        )
        self.assertEqual(throttled.status_code, 429)
        body = throttled.json()
        self.assertEqual(body['status'], 'error')
        self.assertEqual(body['code'], 'throttled')
        self.assertEqual(
            body['message'],
            'Too many login attempts. Please wait before trying again.',
        )
        self.assertIsNone(body['errors'])
        self.assertIsInstance(body['retry_after'], int)
        self.assertGreater(body['retry_after'], 0)
        self.assertIn('Retry-After', throttled)
        self.assertEqual(throttled['Retry-After'], str(body['retry_after']))

    def test_resend_otp_works_for_unverified_user(self):
        from unittest.mock import patch

        with patch('accounts.views.send_otp_email', return_value=True):
            response = self.client.post(
                self.resend_otp_url,
                {'email': 'unverified@example.com'},
                format='json',
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
