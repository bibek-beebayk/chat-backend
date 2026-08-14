from decimal import Decimal

from django.db import migrations


def seed_redemption_config_and_actions(apps, schema_editor):
    PointsRedemptionConfig = apps.get_model('points', 'PointsRedemptionConfig')
    PointAction = apps.get_model('points', 'PointAction')

    PointsRedemptionConfig.objects.get_or_create(
        pk=1,
        defaults={
            'min_redemption_points': 5000,
            'rp_to_credit_rate': Decimal('1.0000'),
        },
    )
    PointAction.objects.get_or_create(
        slug='registration_bonus',
        defaults={'label': 'Registration Bonus', 'points_value': 1000, 'is_active': True},
    )
    PointAction.objects.get_or_create(
        slug='registration_backfill_2026_08',
        defaults={'label': 'Registration Backfill (Aug 2026)', 'points_value': 1000, 'is_active': True},
    )


def unseed_redemption_config_and_actions(apps, schema_editor):
    PointAction = apps.get_model('points', 'PointAction')
    PointAction.objects.filter(slug__in=['registration_bonus', 'registration_backfill_2026_08']).delete()
    # PointsRedemptionConfig singleton intentionally left in place on reverse.


class Migration(migrations.Migration):

    dependencies = [
        ('points', '0005_pointsredemptionrequest_conversion_rate_snapshot_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_redemption_config_and_actions, reverse_code=unseed_redemption_config_and_actions),
    ]
