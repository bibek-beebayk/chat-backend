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
