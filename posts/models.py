from django.db import models
from django.conf import settings
from ckeditor_uploader.fields import RichTextUploadingField

class Post(models.Model):
    """
    Model for posts in the feed (Text, Image, Video).
    """
    VISIBILITY_CHOICES = [
        ('all', 'All'),
        ('players', 'Players'),
        ('agents', 'Agents'),
    ]

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='posts'
    )
    title = models.CharField(max_length=200)
    content = RichTextUploadingField(blank=True)
    image = models.ImageField(upload_to='post_images/', blank=True, null=True)
    video = models.FileField(upload_to='post_videos/', blank=True, null=True)
    link = models.URLField(blank=True, null=True, help_text="Optional link to external content")
    visibility = models.CharField(
        max_length=10,
        choices=VISIBILITY_CHOICES,
        default='all',
        help_text='Who can view this post.',
    )
    is_pinned = models.BooleanField(
        default=False,
        help_text='Whether this post should appear in pinned posts feed.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    # def save(self, *args, **kwargs):
    #     if self.link and not self.link.startswith('http://') and not self.link.startswith('https://'):
    #         self.link = 'http://' + self.link
    #     super().save(*args, **kwargs)
