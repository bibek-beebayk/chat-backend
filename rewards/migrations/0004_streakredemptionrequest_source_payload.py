from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rewards', '0003_scratchredemption'),
    ]

    operations = [
        migrations.AddField(
            model_name='streakredemptionrequest',
            name='source',
            field=models.CharField(
                choices=[
                    ('login_streak', 'Login Streak'),
                    ('scratch_bonus', 'Scratch Bonus'),
                ],
                default='login_streak',
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name='streakredemptionrequest',
            name='amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('5.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='streakredemptionrequest',
            name='source_payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddIndex(
            model_name='streakredemptionrequest',
            index=models.Index(fields=['source', 'status', 'created_at'], name='rewards_str_source_fb3b64_idx'),
        ),
    ]
