from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

STORY_LIFETIME = timedelta(hours=24)


class Story(models.Model):
    """
    A single 24h-expiring story image. Expiry is enforced lazily at query
    time (expires_at__gt=now()) rather than by a cleanup job - this codebase
    has no Celery/cron infra, so a story simply stops being returned once
    its window has passed (same lazy-resolution convention Rocket uses for
    round settlement).
    """
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='stories',
    )
    media = models.ImageField(upload_to='story_media/')
    caption = models.CharField(max_length=280, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(editable=False)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + STORY_LIFETIME
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Story #{self.pk} by {self.author.username}'


class StoryView(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='views')
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='story_views',
    )
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['story', 'viewer'], name='unique_story_view_per_user'),
        ]

    def __str__(self):
        return f'{self.viewer.username} viewed story #{self.story_id}'
