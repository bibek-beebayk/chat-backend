from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from notifications.models import UserPresence
from .models import UserConnection


class ConnectionPresenceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='presence-player',
            email='presence-player@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.friend_online = get_user_model().objects.create_user(
            username='friend-online',
            email='friend-online@example.com',
            password='test-pass-123',
            user_type='player',
        )
        self.friend_no_presence = get_user_model().objects.create_user(
            username='friend-no-presence',
            email='friend-no-presence@example.com',
            password='test-pass-123',
            user_type='player',
        )
        UserPresence.objects.create(user=self.friend_online, status='ONLINE')
        # friend_no_presence deliberately has no UserPresence row.

        UserConnection.objects.create(
            requester=self.user, receiver=self.friend_online,
            connection_type=UserConnection.TYPE_PLAYER_PLAYER, status=UserConnection.STATUS_ACCEPTED,
        )
        UserConnection.objects.create(
            requester=self.user, receiver=self.friend_no_presence,
            connection_type=UserConnection.TYPE_PLAYER_PLAYER, status=UserConnection.STATUS_ACCEPTED,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_presence_status_reflects_real_online_state(self):
        response = self.client.get(reverse('social-connections'))
        self.assertEqual(response.status_code, 200)
        by_username = {row['receiver']['username']: row['receiver'] for row in response.data}
        self.assertEqual(by_username['friend-online']['presence_status'], 'ONLINE')

    def test_presence_status_defaults_to_offline_when_no_presence_row(self):
        response = self.client.get(reverse('social-connections'))
        by_username = {row['receiver']['username']: row['receiver'] for row in response.data}
        self.assertEqual(by_username['friend-no-presence']['presence_status'], 'OFFLINE')

    def test_presence_is_joined_not_queried_separately(self):
        # The real regression this guards: select_related on
        # requester__presence/receiver__presence means presence rows are
        # pulled in via JOIN on the main connections query, never as their
        # own separate SELECT - regardless of how many connections exist,
        # and regardless of any unrelated pre-existing per-user query
        # overhead elsewhere in UserSerializer (out of scope for this fix).
        for i in range(5):
            other = get_user_model().objects.create_user(
                username=f'extra-friend-{i}', email=f'extra-friend-{i}@example.com',
                password='test-pass-123', user_type='player',
            )
            UserPresence.objects.create(user=other, status='ONLINE')
            UserConnection.objects.create(
                requester=self.user, receiver=other,
                connection_type=UserConnection.TYPE_PLAYER_PLAYER, status=UserConnection.STATUS_ACCEPTED,
            )

        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse('social-connections'))

        standalone_presence_queries = [
            q for q in captured.captured_queries
            if 'FROM "notifications_userpresence"' in q['sql'] and 'JOIN' not in q['sql']
        ]
        self.assertEqual(standalone_presence_queries, [])

    def test_last_seen_updates_on_repeated_saves(self):
        # Regression guard for the auto_now_add -> auto_now fix: last_seen
        # must actually update on subsequent saves, not stay frozen at
        # creation time.
        presence = UserPresence.objects.get(user=self.friend_online)
        first_seen = presence.last_seen
        presence.status = 'OFFLINE'
        presence.save()
        presence.refresh_from_db()
        self.assertGreater(presence.last_seen, first_seen)
