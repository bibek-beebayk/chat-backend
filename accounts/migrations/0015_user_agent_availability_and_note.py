from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0014_user_profile_picture_emailchangeotp'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='agent_availability',
            field=models.CharField(
                choices=[
                    ('online', 'Online'),
                    ('busy', 'Busy'),
                    ('away', 'Away'),
                    ('offline', 'Offline'),
                ],
                default='online',
                help_text='Availability status used for direct player-to-agent chat.',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='agent_status_note',
            field=models.CharField(
                blank=True,
                help_text='Optional short note shown to players (e.g. Back in 10 mins).',
                max_length=120,
            ),
        ),
    ]
