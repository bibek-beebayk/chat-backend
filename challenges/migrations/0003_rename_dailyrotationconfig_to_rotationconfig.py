from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('challenges', '0002_dailyrotationconfig'),
    ]

    operations = [
        migrations.RenameModel(old_name='DailyRotationConfig', new_name='RotationConfig'),
        migrations.RenameField(model_name='rotationconfig', old_name='active_count', new_name='daily_active_count'),
        migrations.AlterField(
            model_name='rotationconfig',
            name='daily_active_count',
            field=models.PositiveSmallIntegerField(
                default=3,
                help_text='How many rotation-pool Daily Challenges are live each day. 0 hides the whole pool. A count at or above the pool size shows the entire pool every day (no rotation effect).',
            ),
        ),
        migrations.AddField(
            model_name='rotationconfig',
            name='weekly_active_count',
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text='How many rotation-pool Weekly Challenges are live each week. 0 hides the whole pool. A count at or above the pool size shows the entire pool every week (no rotation effect).',
            ),
        ),
        migrations.AlterModelOptions(
            name='rotationconfig',
            options={'verbose_name': 'Rotation Settings', 'verbose_name_plural': 'Rotation Settings'},
        ),
    ]
