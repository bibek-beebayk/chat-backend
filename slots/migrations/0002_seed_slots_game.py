from django.db import migrations


def seed_slots_game(apps, schema_editor):
    Game = apps.get_model('games', 'Game')
    Game.objects.get_or_create(
        slug='slots',
        defaults={
            'name': 'Rollin 3x3',
            'description': 'A 3-reel, 3-row, 5-payline Rollin-themed slot machine.',
            'is_active': True,
        },
    )


def unseed_slots_game(apps, schema_editor):
    Game = apps.get_model('games', 'Game')
    Game.objects.filter(slug='slots').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('slots', '0001_initial'),
        ('games', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_slots_game, reverse_code=unseed_slots_game),
    ]
