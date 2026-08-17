from django.db import migrations

# Slugs seeded here, called from rocket/xp_hooks.py::grant_rocket_xp - kept
# in one place so the mapping between "what happened in a round" and "which
# XPAction fires" is easy to audit. XP values/caps are ordinary XPAction
# fields, adjustable later via the admin without touching game code.
ROCKET_XP_ACTIONS = [
    {
        'slug': 'rocket_qualified_gameplay',
        'label': 'Rollin Rocket: Qualified Gameplay',
        'xp_value': 2,
        'max_awards_per_day': 25,
    },
    {
        'slug': 'rocket_cashout_above_2x',
        'label': 'Rollin Rocket: Cash Out Above 2x',
        'xp_value': 5,
        'max_awards_per_day': 10,
    },
    {
        'slug': 'rocket_cashout_above_5x',
        'label': 'Rollin Rocket: Cash Out Above 5x',
        'xp_value': 15,
        'max_awards_per_day': 5,
    },
    {
        'slug': 'rocket_cashout_above_10x',
        'label': 'Moon Walker',
        'xp_value': 50,
        'max_awards_per_day': 3,
    },
    {
        'slug': 'rocket_five_alive',
        'label': 'Five Alive',
        'xp_value': 30,
        'max_awards_per_day': 3,
    },
]


def seed_rocket_xp_actions(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    for spec in ROCKET_XP_ACTIONS:
        XPAction.objects.get_or_create(
            slug=spec['slug'],
            defaults={
                'label': spec['label'],
                'xp_value': spec['xp_value'],
                'is_active': True,
                'max_awards_per_day': spec['max_awards_per_day'],
            },
        )


def unseed_rocket_xp_actions(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    XPAction.objects.filter(slug__in=[spec['slug'] for spec in ROCKET_XP_ACTIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('rocket', '0002_seed_rocket_game'),
        ('xp', '0002_seed_xp_actions'),
    ]

    operations = [
        migrations.RunPython(seed_rocket_xp_actions, reverse_code=unseed_rocket_xp_actions),
    ]
