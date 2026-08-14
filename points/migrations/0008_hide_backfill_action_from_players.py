from django.db import migrations


def hide_backfill_action(apps, schema_editor):
    PointAction = apps.get_model('points', 'PointAction')
    PointAction.objects.filter(slug='registration_backfill_2026_08').update(is_visible_to_players=False)


def unhide_backfill_action(apps, schema_editor):
    PointAction = apps.get_model('points', 'PointAction')
    PointAction.objects.filter(slug='registration_backfill_2026_08').update(is_visible_to_players=True)


class Migration(migrations.Migration):

    dependencies = [
        ('points', '0007_pointaction_is_visible_to_players'),
    ]

    operations = [
        migrations.RunPython(hide_backfill_action, reverse_code=unhide_backfill_action),
    ]
