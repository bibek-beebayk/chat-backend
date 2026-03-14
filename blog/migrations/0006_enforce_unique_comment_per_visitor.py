from django.db import migrations, models
from django.db.models import Count


def dedupe_blog_comments(apps, schema_editor):
    BlogComment = apps.get_model('blog', 'BlogComment')

    duplicate_pairs = (
        BlogComment.objects.values('blog_id', 'visitor_hash')
        .annotate(total=Count('id'))
        .filter(total__gt=1)
    )

    for pair in duplicate_pairs:
        items = list(
            BlogComment.objects.filter(
                blog_id=pair['blog_id'],
                visitor_hash=pair['visitor_hash'],
            )
            .order_by('-created_at', '-id')
            .values_list('id', flat=True)
        )
        keep_id = items[0]
        BlogComment.objects.filter(id__in=items[1:]).exclude(id=keep_id).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0005_blogcomment_blogreaction'),
    ]

    operations = [
        migrations.RunPython(dedupe_blog_comments, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='blogcomment',
            constraint=models.UniqueConstraint(
                fields=('blog', 'visitor_hash'),
                name='unique_blog_comment_per_visitor',
            ),
        ),
    ]
