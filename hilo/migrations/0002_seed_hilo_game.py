from django.db import migrations


def create_hilo_game(apps, schema_editor):
    Game = apps.get_model('games', 'Game')
    Game.objects.get_or_create(
        slug='hilo',
        defaults={
            'name': 'Rollin Hi-Lo',
            'description': 'Guess. Climb. Cash Out.',
            'is_active': True,
        },
    )


def delete_hilo_game(apps, schema_editor):
    Game = apps.get_model('games', 'Game')
    Game.objects.filter(slug='hilo').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('hilo', '0001_initial'),
        ('games', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_hilo_game, reverse_code=delete_hilo_game),
    ]
