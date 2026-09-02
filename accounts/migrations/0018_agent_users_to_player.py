from django.db import migrations


def agents_to_players(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(user_type='agent').update(user_type='player')


def players_to_agents(apps, schema_editor):
    # Best-effort reverse: there is no way to know which 'player' rows were
    # previously 'agent', so this is intentionally a no-op.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0017_user_needs_username_setup'),
    ]

    operations = [
        migrations.RunPython(agents_to_players, players_to_agents),
    ]
