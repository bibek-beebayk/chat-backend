from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('xp', '0010_copy_challenge_source_action_to_m2m'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='xpaction',
            name='challenge_source_action',
        ),
    ]
