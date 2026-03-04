from django.db import migrations, models


def forward_update_visibility(apps, schema_editor):
    Post = apps.get_model('posts', 'Post')
    Post.objects.filter(visibility='player').update(visibility='players')
    Post.objects.filter(visibility='staff').update(visibility='all')


def backward_update_visibility(apps, schema_editor):
    Post = apps.get_model('posts', 'Post')
    Post.objects.filter(visibility='players').update(visibility='player')
    # We cannot safely infer old 'staff' from 'all', so keep 'all' unchanged.


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0004_post_visibility'),
    ]

    operations = [
        migrations.RunPython(forward_update_visibility, backward_update_visibility),
        migrations.AlterField(
            model_name='post',
            name='visibility',
            field=models.CharField(
                choices=[('all', 'All'), ('players', 'Players'), ('agents', 'Agents')],
                default='all',
                help_text='Who can view this post.',
                max_length=10,
            ),
        ),
    ]
