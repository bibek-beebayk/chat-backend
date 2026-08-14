from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Post


class PostFeedLimitTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='feed-player',
            email='feed-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        for i in range(5):
            Post.objects.create(title=f'Post {i}', content='body', author=self.user, visibility='public')

    def test_feed_without_limit_returns_all(self):
        response = self.client.get(reverse('post-feed'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 5)

    def test_feed_with_limit_caps_results(self):
        response = self.client.get(reverse('post-feed'), {'limit': 3})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 3)

    def test_feed_limit_is_clamped_to_maximum(self):
        response = self.client.get(reverse('post-feed'), {'limit': 500})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 5)  # only 5 posts exist, clamp doesn't matter here but confirms no error

    def test_feed_limit_invalid_value_falls_back_to_default(self):
        response = self.client.get(reverse('post-feed'), {'limit': 'not-a-number'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 5)  # default=10, still under the 5 real posts

    def test_feed_results_still_most_recent_first_when_limited(self):
        response = self.client.get(reverse('post-feed'), {'limit': 2})
        titles = [p['title'] for p in response.data]
        self.assertEqual(titles, ['Post 4', 'Post 3'])
