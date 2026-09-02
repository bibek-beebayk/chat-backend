from django.db import migrations


GAMEPLAY_ROUND_SLUG = 'gameplay_round'
QUALIFIED_SLUG = 'qualified_gameplay'


def add_gameplay_round_counter(apps, schema_editor):
    """
    "Play N rounds" challenges used to count qualified_gameplay EARN entries,
    but that action is capped at max_awards_per_day=25 (its job is to trickle
    XP, 2 XP x 25 = 50 XP/day). Any challenge_target_count > 25 could never be
    reached and the home "Today's mission" card froze at 25/50.

    Split the two concerns: qualified_gameplay stays the (capped) XP trickle,
    and a new uncapped, zero-XP gameplay_round action is the pure per-round
    counter that "play N rounds" challenges point at.
    """
    XPAction = apps.get_model('xp', 'XPAction')

    counter, _ = XPAction.objects.get_or_create(
        slug=GAMEPLAY_ROUND_SLUG,
        defaults={
            'label': 'Gameplay Round',
            'xp_value': 0,
            'is_active': True,
            'description': 'Uncapped per-round counter for "play N rounds" daily challenges. Awards no XP.',
        },
    )

    # Repoint every challenge that was counting the capped trickle action.
    XPAction.objects.filter(challenge_source_action__slug=QUALIFIED_SLUG).update(
        challenge_source_action=counter,
    )


def remove_gameplay_round_counter(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    try:
        qualified = XPAction.objects.get(slug=QUALIFIED_SLUG)
    except XPAction.DoesNotExist:
        qualified = None
    if qualified is not None:
        XPAction.objects.filter(challenge_source_action__slug=GAMEPLAY_ROUND_SLUG).update(
            challenge_source_action=qualified,
        )
    XPAction.objects.filter(slug=GAMEPLAY_ROUND_SLUG, ledger_entries__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('xp', '0003_xpbalance_pending_celebration_rank'),
    ]

    operations = [
        migrations.RunPython(add_gameplay_round_counter, remove_gameplay_round_counter),
    ]
