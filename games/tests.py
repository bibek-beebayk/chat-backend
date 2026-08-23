from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Game


class GameListViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='games-player',
            email='games-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_only_active_games_are_listed(self):
        Game.objects.create(name='Active Game', slug='active-game', is_active=True)
        Game.objects.create(name='Inactive Game', slug='inactive-game', is_active=False)

        response = self.client.get(reverse('games-list'))

        self.assertEqual(response.status_code, 200)
        slugs = [item['slug'] for item in response.data]
        self.assertIn('active-game', slugs)
        self.assertNotIn('inactive-game', slugs)

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('games-list'))
        self.assertEqual(response.status_code, 401)


from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from plinko.models import PlinkoRound
from rocket.models import RocketRound
from slots.models import SlotRound


def _make_plinko_round(user, game, *, wager_amount=10, multiplier=Decimal('2.00'), created_at=None):
    payout = Decimal(wager_amount) * multiplier
    round_obj = PlinkoRound.objects.create(
        user=user,
        game=game,
        rows=8,
        risk_level='medium',
        wager_amount=wager_amount,
        slot_index=4,
        multiplier=multiplier,
        payout_amount=payout,
        path=[0, 1, 0, 1, 0, 1, 0, 1],
        balance_after=Decimal('1000.00'),
    )
    if created_at:
        PlinkoRound.objects.filter(id=round_obj.id).update(created_at=created_at)
    return round_obj


def _make_slot_round(user, game, *, wager_amount=10, payout_amount=Decimal('0.00'), created_at=None):
    round_obj = SlotRound.objects.create(
        user=user,
        game=game,
        wager_amount=wager_amount,
        reel_1_stop=0,
        reel_2_stop=0,
        reel_3_stop=0,
        grid_snapshot=[[1, 1, 1], [1, 1, 1], [1, 1, 1]],
        total_multiplier=(payout_amount / wager_amount) if payout_amount else Decimal('0.00'),
        payout_amount=payout_amount,
        net_result=payout_amount - wager_amount,
        balance_before=Decimal('1000.00'),
        balance_after=Decimal('1000.00'),
    )
    if created_at:
        SlotRound.objects.filter(id=round_obj.id).update(created_at=created_at)
    return round_obj


def _make_rocket_round(user, game, *, wager_amount=Decimal('10.00'), status=RocketRound.STATUS_CRASHED,
                        cashout_multiplier=None, created_at=None):
    round_obj = RocketRound.objects.create(
        user=user,
        game=game,
        wager_amount=wager_amount,
        crash_point=Decimal('2.50'),
        started_at=timezone.now(),
        status=status,
        cashout_multiplier=cashout_multiplier,
        payout_amount=(wager_amount * cashout_multiplier) if cashout_multiplier else Decimal('0.00'),
    )
    if created_at:
        RocketRound.objects.filter(id=round_obj.id).update(created_at=created_at)
    return round_obj


class PlayerStatsViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='stats-player',
            email='stats-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        # These slugs are already seeded via migrations (plinko/slots/rocket
        # apps each seed their own Game row) - fetch rather than create to
        # avoid colliding with the seeded rows in every test database.
        self.plinko_game, _ = Game.objects.get_or_create(slug='plinko', defaults={'name': 'Plinko'})
        self.slots_game, _ = Game.objects.get_or_create(slug='slots', defaults={'name': 'Rollin 3x3'})
        self.rocket_game, _ = Game.objects.get_or_create(slug='rocket', defaults={'name': 'Rollin Rocket'})
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_aggregates_rounds_wins_and_highest_multiplier_across_games(self):
        _make_plinko_round(self.user, self.plinko_game, wager_amount=10, multiplier=Decimal('3.00'))  # win
        _make_plinko_round(self.user, self.plinko_game, wager_amount=10, multiplier=Decimal('0.50'))  # loss
        _make_slot_round(self.user, self.slots_game, wager_amount=10, payout_amount=Decimal('0.00'))  # loss
        _make_rocket_round(self.user, self.rocket_game, status=RocketRound.STATUS_CASHED_OUT, cashout_multiplier=Decimal('12.00'))  # win

        response = self.client.get(reverse('games-player-stats'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['rounds_played'], 4)
        self.assertEqual(response.data['total_wins'], 2)
        self.assertEqual(Decimal(response.data['highest_multiplier']), Decimal('12.00'))

    def test_week_range_excludes_older_rounds(self):
        old = timezone.now() - timedelta(days=30)
        _make_plinko_round(self.user, self.plinko_game, wager_amount=10, multiplier=Decimal('5.00'), created_at=old)
        _make_plinko_round(self.user, self.plinko_game, wager_amount=10, multiplier=Decimal('2.00'))

        response = self.client.get(reverse('games-player-stats'), {'range': 'week'})
        self.assertEqual(response.data['rounds_played'], 1)
        self.assertEqual(Decimal(response.data['highest_multiplier']), Decimal('2.00'))

    def test_no_rounds_returns_null_highest_multiplier(self):
        response = self.client.get(reverse('games-player-stats'))
        self.assertEqual(response.data['rounds_played'], 0)
        self.assertEqual(response.data['total_wins'], 0)
        self.assertIsNone(response.data['highest_multiplier'])

    def test_invalid_range_falls_back_to_all(self):
        response = self.client.get(reverse('games-player-stats'), {'range': 'bogus'})
        self.assertEqual(response.data['range'], 'all')

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('games-player-stats'))
        self.assertEqual(response.status_code, 401)
