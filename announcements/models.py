from django.conf import settings
from django.db import models
from django.utils import timezone
from ckeditor_uploader.fields import RichTextUploadingField


class Announcement(models.Model):
    CATEGORY_GENERAL = 'general'
    CATEGORY_EVENT = 'event'
    CATEGORY_REWARD = 'reward'
    CATEGORY_MAINTENANCE = 'maintenance'
    CATEGORY_SECURITY = 'security'
    CATEGORY_VIP = 'vip'
    CATEGORY_CHOICES = [
        (CATEGORY_GENERAL, 'General'),
        (CATEGORY_EVENT, 'Event'),
        (CATEGORY_REWARD, 'Reward'),
        (CATEGORY_MAINTENANCE, 'Maintenance'),
        (CATEGORY_SECURITY, 'Security'),
        (CATEGORY_VIP, 'VIP'),
    ]

    AUDIENCE_ALL = 'all'
    AUDIENCE_PLAYERS = 'players'
    AUDIENCE_AGENTS = 'agents'
    AUDIENCE_STAFF = 'staff'
    AUDIENCE_CHOICES = [
        (AUDIENCE_ALL, 'All Members'),
        (AUDIENCE_PLAYERS, 'Players'),
        (AUDIENCE_AGENTS, 'Agents'),
        (AUDIENCE_STAFF, 'Staff'),
    ]

    PRIORITY_NORMAL = 'normal'
    PRIORITY_IMPORTANT = 'important'
    PRIORITY_URGENT = 'urgent'
    PRIORITY_CHOICES = [
        (PRIORITY_NORMAL, 'Normal'),
        (PRIORITY_IMPORTANT, 'Important'),
        (PRIORITY_URGENT, 'Urgent'),
    ]

    title = models.CharField(max_length=220)
    summary = models.CharField(max_length=360, blank=True)
    content = RichTextUploadingField(blank=True)
    cover_image = models.ImageField(upload_to='announcement_covers/', blank=True, null=True)
    category = models.CharField(max_length=24, choices=CATEGORY_CHOICES, default=CATEGORY_GENERAL)
    audience = models.CharField(max_length=16, choices=AUDIENCE_CHOICES, default=AUDIENCE_ALL)
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL)
    is_pinned = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_announcements',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_pinned', '-published_at', '-created_at']
        indexes = [
            models.Index(fields=['is_published', 'audience', 'published_at']),
            models.Index(fields=['is_pinned', 'published_at']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.is_published and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)
