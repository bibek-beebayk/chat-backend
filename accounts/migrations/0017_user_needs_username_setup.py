from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0016_user_profile_thumbnail'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='needs_username_setup',
            field=models.BooleanField(
                default=False,
                help_text='Designates whether the user should choose a public username.',
            ),
        ),
    ]
