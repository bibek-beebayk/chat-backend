from django.db import migrations

# Turns the two previously-hardcoded Python lists in xp/views.py
# (DAILY_CHECKLIST_SLUGS and ACHIEVEMENT_DEFINITIONS) into data, plus the
# per-slug label/icon/link maps that used to live in the frontend. Values
# here reproduce exactly what those lists and maps rendered before, so this
# migration changes no player-visible output - it only moves the source of
# truth into the database, where staff can edit it.
CHECKLIST = [
    {
        'slug': 'daily_login',
        'display_order': 10,
        'icon': '📅',
        'action_url': '',  # nothing to do - it completes just by logging in
    },
    {
        'slug': 'daily_challenge_rounds',
        'display_order': 20,
        'icon': '🎲',
        'action_url': '/games/plinko',
        # {target} is substituted from challenge_target_count at read time
        # (see XPAction.display_label), so retuning the target in admin
        # keeps the label honest. This is what the frontend used to
        # interpolate for this one slug.
        'label': 'Daily Challenge: Play {target} Rounds',
    },
]

ACHIEVEMENTS = [
    # Order and labels match the old ACHIEVEMENT_DEFINITIONS list exactly.
    {'slug': 'streak_7day', 'display_order': 10, 'label': '7-Day Streak', 'icon': '🔥'},
    {'slug': 'first_win', 'display_order': 20, 'label': 'First Win', 'icon': '🏆'},
    {'slug': 'rocket_cashout_above_10x', 'display_order': 30, 'icon': '🚀'},
    {'slug': 'rocket_five_alive', 'display_order': 40, 'icon': '🖐'},
    {'slug': 'hilo_streak_10', 'display_order': 50, 'icon': '🃏'},
]


def flag_rows(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')

    for spec in CHECKLIST:
        action = XPAction.objects.filter(slug=spec['slug']).first()
        if not action:
            continue
        action.is_daily_checklist = True
        action.display_order = spec['display_order']
        action.icon = spec['icon']
        action.action_url = spec['action_url']
        if 'label' in spec:
            action.label = spec['label']
        action.save()

    # "First Win" was never an XPAction - it was a special entry in the
    # hardcoded list, unlocked by a live cross-game query rather than an XP
    # award (see xp/views.py::_has_first_win, which still decides it). It
    # gets a row here purely so the achievement list can be one ordered
    # database query instead of a list with an exception in it. Nothing
    # awards this slug, hence xp_value=0.
    XPAction.objects.get_or_create(
        slug='first_win',
        defaults={
            'label': 'First Win',
            'xp_value': 0,
            'is_active': True,
            'description': 'Unlocked by winning a round in any game - not awarded as XP.',
        },
    )

    for spec in ACHIEVEMENTS:
        action = XPAction.objects.filter(slug=spec['slug']).first()
        if not action:
            continue
        action.is_achievement = True
        action.display_order = spec['display_order']
        action.icon = spec['icon']
        if 'label' in spec:
            action.label = spec['label']
        action.save()


def unflag_rows(apps, schema_editor):
    XPAction = apps.get_model('xp', 'XPAction')
    slugs = [s['slug'] for s in CHECKLIST] + [s['slug'] for s in ACHIEVEMENTS]
    XPAction.objects.filter(slug__in=slugs).update(
        is_daily_checklist=False,
        is_achievement=False,
        display_order=100,
        icon='',
        action_url='',
    )
    XPAction.objects.filter(slug='first_win').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('xp', '0006_xpaction_action_url_xpaction_display_order_and_more'),
        # Flags rocket_cashout_above_10x, rocket_five_alive, and
        # hilo_streak_10 as achievements below - those XPAction rows are
        # created by these games' own seed migrations, not xp's. Without
        # this dependency the migration graph has no ordering constraint
        # between them and xp.0007, so a legal topological sort can (and,
        # once enough other migrations add unrelated cross-app edges
        # elsewhere in the graph, eventually will) run this migration
        # before those rows exist - flag_rows() below finds nothing to
        # flag and silently no-ops for them. Explicit dependencies close
        # that gap.
        ('rocket', '0003_seed_rocket_xp_actions'),
        ('hilo', '0003_seed_hilo_xp_actions'),
    ]

    operations = [
        migrations.RunPython(flag_rows, reverse_code=unflag_rows),
    ]
