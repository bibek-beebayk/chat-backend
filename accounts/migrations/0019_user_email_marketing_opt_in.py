from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0018_agent_users_to_player'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='email_marketing_opt_in',
            field=models.BooleanField(
                default=False,
                help_text='User agreed to receive email updates about offers and rewards.',
            ),
        ),
    ]
