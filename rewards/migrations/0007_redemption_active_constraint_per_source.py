from django.db import migrations, models
import django.db.models.query_utils


class Migration(migrations.Migration):

    dependencies = [
        ('rewards', '0006_add_win_bonus_redemption_source'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='streakredemptionrequest',
            name='unique_active_streak_redemption_per_user',
        ),
        migrations.AddConstraint(
            model_name='streakredemptionrequest',
            constraint=models.UniqueConstraint(
                condition=django.db.models.query_utils.Q(('status__in', ['pending', 'approved'])),
                fields=('user', 'source'),
                name='unique_active_redemption_per_user_source',
            ),
        ),
    ]
