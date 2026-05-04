from django.db import models
from django.conf import settings
from ckeditor_uploader.fields import RichTextUploadingField


class Post(models.Model):
    """
    Model for posts in the feed (Text, Image, Video).
    """
    VISIBILITY_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private'),
        ('connections', 'Connections'),
        # Legacy values kept for backward compat
        ('all', 'All'),
        ('players', 'Players'),
        ('agents', 'Agents'),
    ]

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='posts'
    )
    title = models.CharField(max_length=200, blank=True, default='')
    content = RichTextUploadingField(blank=True)
    image = models.ImageField(upload_to='post_images/', blank=True, null=True)
    video = models.FileField(upload_to='post_videos/', blank=True, null=True)
    link = models.URLField(blank=True, null=True, help_text="Optional link to external content")
    visibility = models.CharField(
        max_length=15,
        choices=VISIBILITY_CHOICES,
        default='public',
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
        return self.title or f'Post #{self.id}'


class PostImage(models.Model):
    """
    Individual image attached to a Post. Supports multi-image posts.
    """
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='images',
    )
    image = models.ImageField(upload_to='post_images/')
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'Image {self.order} for Post #{self.post_id}'


class PostLike(models.Model):
    """
    Like relationship between a user and a post.
    One user can like a post only once.
    """
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='likes',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='post_likes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['post', 'user'], name='unique_post_like')
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'Like(user={self.user_id}, post={self.post_id})'


class PostComment(models.Model):
    """
    Post comment model supporting nested replies.
    """
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='comments',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='post_comments',
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        related_name='replies',
        null=True,
        blank=True,
    )
    content = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f'Comment #{self.id} on Post #{self.post_id}'
