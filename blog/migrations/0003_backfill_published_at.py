from django.db import migrations


def forward_fill_published_at(apps, schema_editor):
    Blog = apps.get_model('blog', 'Blog')
    for blog in Blog.objects.filter(is_published=True, published_at__isnull=True):
        blog.published_at = blog.created_at
        blog.save(update_fields=['published_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0002_blog_seo_fields'),
    ]

    operations = [
        migrations.RunPython(forward_fill_published_at, migrations.RunPython.noop),
    ]

