from django.conf import settings
from django.db import models


class ActivityEvent(models.Model):
    KIND_ACCOUNT = 'account'
    KIND_POST = 'post'
    KIND_COMMENT = 'comment'
    KIND_EVENT = 'event'
    KIND_REWARD = 'reward'
    KIND_CHOICES = [
        (KIND_ACCOUNT, 'Account'),
        (KIND_POST, 'Post'),
        (KIND_COMMENT, 'Comment'),
        (KIND_EVENT, 'Event'),
        (KIND_REWARD, 'Reward'),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='activity_events',
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=24, choices=KIND_CHOICES)
    action = models.CharField(max_length=160)
    target_title = models.CharField(max_length=200, blank=True, default='')
    target_url = models.CharField(max_length=255, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['kind', '-created_at']),
        ]

    def __str__(self):
        actor = self.actor.username if self.actor_id and self.actor else 'System'
        return f'{actor} {self.action}'


class AnalyticsEvent(models.Model):
    EVENT_PAGE_VIEW = 'page_view'
    EVENT_REGISTER = 'register'
    EVENT_LOGIN = 'login'
    EVENT_LOGOUT = 'logout'
    EVENT_REDEMPTION = 'redemption'
    EVENT_EVENT_REGISTRATION = 'event_registration'
    EVENT_CUSTOM = 'custom'
    EVENT_CHOICES = [
        (EVENT_PAGE_VIEW, 'Page View'),
        (EVENT_REGISTER, 'Register'),
        (EVENT_LOGIN, 'Login'),
        (EVENT_LOGOUT, 'Logout'),
        (EVENT_REDEMPTION, 'Redemption'),
        (EVENT_EVENT_REGISTRATION, 'Event Registration'),
        (EVENT_CUSTOM, 'Custom'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='analytics_events',
        null=True,
        blank=True,
    )
    anonymous_id = models.CharField(max_length=80, blank=True, default='')
    session_id = models.CharField(max_length=80, blank=True, default='')
    event_type = models.CharField(max_length=40, choices=EVENT_CHOICES, db_index=True)
    event_name = models.CharField(max_length=120, blank=True, default='')
    user_type = models.CharField(max_length=20, blank=True, default='', db_index=True)
    path = models.CharField(max_length=255, blank=True, default='', db_index=True)
    full_path = models.CharField(max_length=500, blank=True, default='')
    method = models.CharField(max_length=12, blank=True, default='')
    referrer = models.CharField(max_length=500, blank=True, default='')
    source = models.CharField(max_length=120, blank=True, default='', db_index=True)
    medium = models.CharField(max_length=120, blank=True, default='')
    campaign = models.CharField(max_length=160, blank=True, default='')
    device_type = models.CharField(max_length=40, blank=True, default='', db_index=True)
    browser = models.CharField(max_length=80, blank=True, default='')
    os = models.CharField(max_length=80, blank=True, default='')
    country = models.CharField(max_length=80, blank=True, default='')
    region = models.CharField(max_length=120, blank=True, default='')
    city = models.CharField(max_length=120, blank=True, default='')
    ip_hash = models.CharField(max_length=64, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', '-created_at']),
            models.Index(fields=['user_type', '-created_at']),
            models.Index(fields=['path', '-created_at']),
            models.Index(fields=['source', '-created_at']),
        ]

    def __str__(self):
        actor = self.user.username if self.user_id and self.user else self.anonymous_id or 'Anonymous'
        return f'{actor} {self.event_type} {self.path or self.event_name}'
