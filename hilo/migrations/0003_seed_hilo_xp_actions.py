from django.db import migrations

# Slugs seeded here, called from hilo/xp_hooks.py::grant_hilo_xp - kept in
# one place so the mapping between "what happened in a round" and "which
# XPAction fires" is easy to audit. XP values/caps are ordinary XPAction
# fields, adjustable later via the admin without touching game code.
HILO_XP_ACTIONS = [
    {
        'slug': 'hilo_qualified_gameplay',
        'label': 'Rollin Hi-Lo: Qualified Gameplay',
        'xp_value': 2,
        'max_awards_per_day': 25,
    },
    {
        'slug': 'hilo_cashout_above_2x',
        'label': 'Rollin Hi-Lo: Cash Out Above 2x',
        'xp_value': 5,
        'max_awards_per_day': 10,
    },
    {
        'slug': 'hilo_cashout_above_5x',
        'label': 'Rollin Hi-Lo: Cash Out Above 5x',
        'xp_value': 15,
        'max_awards_per_day': 5,
    },
    {
        'slug': 'hilo_cashout_above_10x',
        'label': 'High Roller',
        'xp_value': 50,
        'max_awards_per_day': 3,
    },
    {
        'slug': 'hilo_streak_5',
        'label': 'Hot Streak',
        'xp_value': 30,
        'max_awards_per_day': 5,
    },
    {
        'slug': 'hilo_streak_10',
        'label': 'Card Counter',
        'xp_value': 75,
        'max_awards_per_day': 3,
    },
]


def seed_hilo_xp_actions(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    for spec in HILO_XP_ACTIONS:
        XPAction.objects.get_or_create(
            slug=spec['slug'],
            defaults={
                'label': spec['label'],
                'xp_value': spec['xp_value'],
                'is_active': True,
                'max_awards_per_day': spec['max_awards_per_day'],
            },
        )


def unseed_hilo_xp_actions(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    XPAction.objects.filter(slug__in=[spec['slug'] for spec in HILO_XP_ACTIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('hilo', '0002_seed_hilo_game'),
        ('xp', '0002_seed_xp_actions'),
    ]

    operations = [
        migrations.RunPython(seed_hilo_xp_actions, reverse_code=unseed_hilo_xp_actions),
    ]
