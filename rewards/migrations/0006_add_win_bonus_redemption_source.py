from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rewards', '0005_scratchrewardclaim'),
    ]

    operations = [
        migrations.AlterField(
            model_name='streakredemptionrequest',
            name='source',
            field=models.CharField(
                choices=[
                    ('login_streak', 'Login Streak'),
                    ('scratch_bonus', 'Scratch Bonus'),
                    ('win_bonus', 'Win Bonus'),
                ],
                default='login_streak',
                max_length=32,
            ),
        ),
    ]
