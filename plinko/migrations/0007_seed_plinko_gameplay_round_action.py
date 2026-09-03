from django.db import migrations

# Uncapped, zero-XP, per-round counter scoped to Plinko only - mirrors the
# shared xp.gameplay_round action (see xp/migrations/0004), but lets a
# challenge be scoped to just this game by listing this action (instead of
# the shared one) in its challenge_source_actions. See rocket/migrations
# and hilo/migrations for the same counter in those games, and
# xp/admin.py's Challenge fieldset help text for how staff picks between
# them.


def create_plinko_gameplay_round_action(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    XPAction.objects.get_or_create(
        slug='plinko_gameplay_round',
        defaults={
            'label': 'Plinko Rounds',
            'xp_value': 0,
            'is_active': True,
            'description': 'Uncapped per-round counter, Plinko only. Lets a challenge be scoped to just this game.',
        },
    )


def delete_plinko_gameplay_round_action(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    XPAction.objects.filter(slug='plinko_gameplay_round').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('plinko', '0006_plinkoround_physics_seed'),
        ('xp', '0011_remove_challenge_source_action'),
    ]

    operations = [
        migrations.RunPython(create_plinko_gameplay_round_action, reverse_code=delete_plinko_gameplay_round_action),
    ]
