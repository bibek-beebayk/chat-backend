from django.db import migrations

# Uncapped, zero-XP, per-round counter scoped to Rocket only - see
# plinko/migrations/0007_seed_plinko_gameplay_round_action.py for the full
# rationale (same pattern, one per game).


def create_rocket_gameplay_round_action(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    XPAction.objects.get_or_create(
        slug='rocket_gameplay_round',
        defaults={
            'label': 'Rocket Rounds',
            'xp_value': 0,
            'is_active': True,
            'description': 'Uncapped per-round counter, Rollin Rocket only. Lets a challenge be scoped to just this game.',
        },
    )


def delete_rocket_gameplay_round_action(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    XPAction.objects.filter(slug='rocket_gameplay_round').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('rocket', '0003_seed_rocket_xp_actions'),
        ('xp', '0011_remove_challenge_source_action'),
    ]

    operations = [
        migrations.RunPython(create_rocket_gameplay_round_action, reverse_code=delete_rocket_gameplay_round_action),
    ]
