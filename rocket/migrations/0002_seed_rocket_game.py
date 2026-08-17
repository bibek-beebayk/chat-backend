from django.db import migrations


def create_rocket_game(apps, schema_editor):
    Game = apps.get_model('games', 'Game')
    Game.objects.get_or_create(
        slug='rocket',
        defaults={
            'name': 'Rollin Rocket',
            'description': 'Cash out before the rocket crashes.',
            'is_active': True,
        },
    )


def delete_rocket_game(apps, schema_editor):
    Game = apps.get_model('games', 'Game')
    Game.objects.filter(slug='rocket').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('rocket', '0001_initial'),
        ('games', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_rocket_game, reverse_code=delete_rocket_game),
    ]
