from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ActivityEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('account', 'Account'), ('post', 'Post'), ('comment', 'Comment'), ('event', 'Event'), ('reward', 'Reward')], max_length=24)),
                ('action', models.CharField(max_length=160)),
                ('target_title', models.CharField(blank=True, default='', max_length=200)),
                ('target_url', models.CharField(blank=True, default='', max_length=255)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='activity_events', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='activityevent',
            index=models.Index(fields=['-created_at'], name='analytics_a_created_9084ab_idx'),
        ),
        migrations.AddIndex(
            model_name='activityevent',
            index=models.Index(fields=['kind', '-created_at'], name='analytics_a_kind_11ef0e_idx'),
        ),
    ]
