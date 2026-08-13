from django.db import migrations


def create_plinko_game(apps, schema_editor):
    Game = apps.get_model('games', 'Game')
    Game.objects.get_or_create(
        slug='plinko',
        defaults={
            'name': 'Plinko',
            'description': 'Drop the ball, bet on the bounce.',
            'is_active': True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('plinko', '0001_initial'),
        ('games', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_plinko_game, reverse_code=migrations.RunPython.noop),
    ]
