from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Blog
from .revalidation import trigger_blog_frontend_revalidation


def _paths_for_blog(blog: Blog):
    paths = ['/', '/sitemap.xml']
    if blog.slug:
        paths.append(f'/blog/{blog.slug}')
    return paths


@receiver(post_save, sender=Blog)
def revalidate_blog_on_save(sender, instance: Blog, **kwargs):
    trigger_blog_frontend_revalidation(_paths_for_blog(instance))


@receiver(post_delete, sender=Blog)
def revalidate_blog_on_delete(sender, instance: Blog, **kwargs):
    trigger_blog_frontend_revalidation(_paths_for_blog(instance))
