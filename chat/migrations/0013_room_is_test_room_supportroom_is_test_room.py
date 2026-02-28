from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0012_alter_supportroom_room_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='room',
            name='is_test_room',
            field=models.BooleanField(
                default=False,
                help_text='If true, this chat room is isolated for test users/staff.',
            ),
        ),
        migrations.AddField(
            model_name='supportroom',
            name='is_test_room',
            field=models.BooleanField(
                default=False,
                help_text='If true, this support room is visible only to test users/staff.',
            ),
        ),
    ]
