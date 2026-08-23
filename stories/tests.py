import base64
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from social.models import UserConnection

from .models import Story, StoryView

# 1x1 transparent PNG - real, Pillow-valid image bytes so ImageField
# validation passes.
TINY_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
)


def make_png(name='story.png'):
    return SimpleUploadedFile(name, TINY_PNG, content_type='image/png')


class StoryVisibilityAndExpiryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user(username='story-author', email='story-author@example.com', password='x', user_type='player')
        self.friend = User.objects.create_user(username='story-friend', email='story-friend@example.com', password='x', user_type='player')
        self.stranger = User.objects.create_user(username='story-stranger', email='story-stranger@example.com', password='x', user_type='player')
        UserConnection.objects.create(requester=self.author, receiver=self.friend, status=UserConnection.STATUS_ACCEPTED)

        self.client = APIClient()

    def test_connection_sees_active_story_stranger_does_not(self):
        Story.objects.create(author=self.author, media=make_png())

        self.client.force_authenticate(self.friend)
        response = self.client.get('/api/stories/')
        author_ids = [group['author']['id'] for group in response.data]
        self.assertIn(self.author.id, author_ids)

        self.client.force_authenticate(self.stranger)
        response = self.client.get('/api/stories/')
        author_ids = [group['author']['id'] for group in response.data]
        self.assertNotIn(self.author.id, author_ids)

    def test_expired_story_is_not_returned(self):
        story = Story.objects.create(author=self.author, media=make_png())
        Story.objects.filter(id=story.id).update(expires_at=timezone.now() - timedelta(minutes=1))

        self.client.force_authenticate(self.friend)
        response = self.client.get('/api/stories/')
        author_ids = [group['author']['id'] for group in response.data]
        self.assertNotIn(self.author.id, author_ids)

    def test_own_story_never_marked_unviewed(self):
        Story.objects.create(author=self.author, media=make_png())

        self.client.force_authenticate(self.author)
        response = self.client.get('/api/stories/')
        own_group = next(g for g in response.data if g['author']['id'] == self.author.id)
        self.assertTrue(own_group['is_own'])
        self.assertFalse(own_group['has_unviewed'])

    def test_mark_viewed_is_idempotent_and_updates_has_unviewed(self):
        story = Story.objects.create(author=self.author, media=make_png())

        self.client.force_authenticate(self.friend)
        response = self.client.get('/api/stories/')
        group = next(g for g in response.data if g['author']['id'] == self.author.id)
        self.assertTrue(group['has_unviewed'])

        view_response = self.client.post(f'/api/stories/{story.id}/view/')
        self.assertEqual(view_response.status_code, status.HTTP_200_OK)
        # calling it again must not create a second row (unique constraint)
        self.client.post(f'/api/stories/{story.id}/view/')
        self.assertEqual(StoryView.objects.filter(story=story, viewer=self.friend).count(), 1)

        response = self.client.get('/api/stories/')
        group = next(g for g in response.data if g['author']['id'] == self.author.id)
        self.assertFalse(group['has_unviewed'])

    def test_stranger_cannot_mark_viewed(self):
        story = Story.objects.create(author=self.author, media=make_png())
        self.client.force_authenticate(self.stranger)
        response = self.client.post(f'/api/stories/{story.id}/view/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_story_via_upload(self):
        self.client.force_authenticate(self.author)
        response = self.client.post('/api/stories/', {'media': make_png(), 'caption': 'hello'}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Story.objects.filter(author=self.author).count(), 1)

    def test_only_author_can_delete(self):
        story = Story.objects.create(author=self.author, media=make_png())

        self.client.force_authenticate(self.friend)
        response = self.client.delete(f'/api/stories/{story.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(self.author)
        response = self.client.delete(f'/api/stories/{story.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Story.objects.filter(id=story.id).exists())
