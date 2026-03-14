from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.utils import timezone
from ckeditor_uploader.fields import RichTextUploadingField


class Blog(models.Model):
    """
    Public blog content model.
    """
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='blog_posts',
    )
    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=260, unique=True, blank=True)
    excerpt = models.CharField(max_length=320, blank=True)
    meta_title = models.CharField(max_length=220, blank=True)
    meta_description = models.CharField(max_length=320, blank=True)
    content = RichTextUploadingField(blank=True)
    cover_image = models.ImageField(upload_to='blog_covers/', blank=True, null=True)
    og_image = models.ImageField(upload_to='blog_og/', blank=True, null=True)
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)[:220] or 'blog'
            slug = base_slug
            suffix = 1
            while Blog.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            self.slug = slug
        if self.is_published and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)


class BlogReaction(models.Model):
    REACTION_LIKE = 'like'
    REACTION_CHOICES = [
        (REACTION_LIKE, 'Like'),
    ]

    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name='reactions')
    visitor_hash = models.CharField(max_length=64, db_index=True)
    reaction_type = models.CharField(max_length=16, choices=REACTION_CHOICES, default=REACTION_LIKE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['blog', 'visitor_hash'], name='unique_blog_reaction_per_visitor')
        ]

    def __str__(self):
        return f'{self.blog_id}:{self.reaction_type}'


class BlogComment(models.Model):
    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name='comments')
    visitor_hash = models.CharField(max_length=64, db_index=True)
    display_name = models.CharField(max_length=80, default='Guest')
    content = models.TextField()
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['blog', 'visitor_hash'], name='unique_blog_comment_per_visitor')
        ]

    def __str__(self):
        return f'{self.blog_id}:{self.display_name}'
