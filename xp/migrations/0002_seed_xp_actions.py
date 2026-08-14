from django.db import migrations


def seed_xp_actions(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')

    XPAction.objects.get_or_create(
        slug='registration',
        defaults={'label': 'Registration', 'xp_value': 10, 'is_active': True},
    )
    XPAction.objects.get_or_create(
        slug='daily_login',
        defaults={'label': 'Daily Login', 'xp_value': 10, 'is_active': True},
    )
    XPAction.objects.get_or_create(
        slug='streak_7day',
        defaults={'label': '7-Day Login Streak', 'xp_value': 30, 'is_active': True},
    )
    qualified_gameplay, _ = XPAction.objects.get_or_create(
        slug='qualified_gameplay',
        defaults={
            'label': 'Qualified Gameplay',
            'xp_value': 2,
            'is_active': True,
            'max_awards_per_day': 25,  # 2 XP x 25/day = 50 XP/day cap
        },
    )
    XPAction.objects.get_or_create(
        slug='daily_challenge_rounds',
        defaults={
            'label': 'Daily Challenge: Play 3 Rounds',
            'xp_value': 30,
            'is_active': True,
            'max_awards_per_day': 1,
            'challenge_target_count': 3,
            'challenge_source_action': qualified_gameplay,
        },
    )


def unseed_xp_actions(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    XPAction.objects.filter(slug__in=[
        'registration', 'daily_login', 'streak_7day', 'qualified_gameplay', 'daily_challenge_rounds',
    ]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('xp', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_xp_actions, reverse_code=unseed_xp_actions),
    ]
