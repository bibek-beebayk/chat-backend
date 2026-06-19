from django.conf import settings
from django.db import models
from django.utils import timezone
from ckeditor_uploader.fields import RichTextUploadingField


class FAQ(models.Model):
    CATEGORY_ACCOUNT = 'account'
    CATEGORY_COMMUNITY = 'community'
    CATEGORY_REWARDS = 'rewards'
    CATEGORY_EVENTS = 'events'
    CATEGORY_SECURITY = 'security'
    CATEGORY_TECHNICAL = 'technical'
    CATEGORY_CHOICES = [
        (CATEGORY_ACCOUNT, 'Account'),
        (CATEGORY_COMMUNITY, 'Community'),
        (CATEGORY_REWARDS, 'Rewards'),
        (CATEGORY_EVENTS, 'Events'),
        (CATEGORY_SECURITY, 'Security'),
        (CATEGORY_TECHNICAL, 'Technical'),
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

    question = models.CharField(max_length=260)
    answer = RichTextUploadingField()
    category = models.CharField(max_length=24, choices=CATEGORY_CHOICES, default=CATEGORY_ACCOUNT)
    audience = models.CharField(max_length=16, choices=AUDIENCE_CHOICES, default=AUDIENCE_ALL)
    sort_order = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_faqs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'FAQ'
        verbose_name_plural = 'FAQs'
        ordering = ['sort_order', '-is_featured', '-published_at', 'question']
        indexes = [
            models.Index(fields=['is_published', 'audience', 'category']),
            models.Index(fields=['sort_order', 'category']),
        ]

    def __str__(self):
        return self.question

    def save(self, *args, **kwargs):
        if self.is_published and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)
