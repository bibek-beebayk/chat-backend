from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0005_post_visibility_players_agents'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='is_pinned',
            field=models.BooleanField(
                default=False,
                help_text='Whether this post should appear in pinned posts feed.',
            ),
        ),
    ]
