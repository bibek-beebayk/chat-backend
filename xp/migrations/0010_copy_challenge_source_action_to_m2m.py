from django.db import migrations


def copy_fk_to_m2m(apps, schema_editor):
    """
    Preserves every existing single-source challenge's configuration (e.g.
    daily_challenge_rounds -> gameplay_round) across the FK-to-M2M switch -
    both fields exist side by side at this point in migration history (the
    old FK is dropped in 0011, after this runs), so this is a pure data
    copy, not a behavior change.
    """
    XPAction = apps.get_model('xp', 'XPAction')
    for action in XPAction.objects.exclude(challenge_source_action__isnull=True):
        action.challenge_source_actions.add(action.challenge_source_action)


def uncopy_m2m_to_fk(apps, schema_editor):
    """Reverse: pick any one source back out for the FK (lossy if more than one was added since - matches the fact that the FK could only ever hold one)."""
    XPAction = apps.get_model('xp', 'XPAction')
    for action in XPAction.objects.all():
        first_source = action.challenge_source_actions.first()
        if first_source:
            action.challenge_source_action = first_source
            action.save(update_fields=['challenge_source_action'])


class Migration(migrations.Migration):

    dependencies = [
        ('xp', '0009_add_challenge_source_actions'),
    ]

    operations = [
        migrations.RunPython(copy_fk_to_m2m, reverse_code=uncopy_m2m_to_fk),
    ]
