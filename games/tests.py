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
