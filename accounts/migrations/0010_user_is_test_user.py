from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_appversion'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_test_user',
            field=models.BooleanField(
                default=False,
                help_text='Designates whether this account is isolated to test support rooms.',
            ),
        ),
    ]
