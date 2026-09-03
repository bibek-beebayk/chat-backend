from django.db import migrations

# Uncapped, zero-XP, per-round counter scoped to Hi-Lo only - see
# plinko/migrations/0007_seed_plinko_gameplay_round_action.py for the full
# rationale (same pattern, one per game).


def create_hilo_gameplay_round_action(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    XPAction.objects.get_or_create(
        slug='hilo_gameplay_round',
        defaults={
            'label': 'Hi-Lo Rounds',
            'xp_value': 0,
            'is_active': True,
            'description': 'Uncapped per-round counter, Rollin Hi-Lo only. Lets a challenge be scoped to just this game.',
        },
    )


def delete_hilo_gameplay_round_action(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    XPAction.objects.filter(slug='hilo_gameplay_round').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('hilo', '0003_seed_hilo_xp_actions'),
        ('xp', '0011_remove_challenge_source_action'),
    ]

    operations = [
        migrations.RunPython(create_hilo_gameplay_round_action, reverse_code=delete_hilo_gameplay_round_action),
    ]
