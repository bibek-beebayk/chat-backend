"""
The dedicated "Challenges" sidebar section: three focused admin screens
(Daily/Weekly/Special) instead of one long XPAction list. Each is scoped to
its period by the proxy model's manager (see models.py) and locks the
period on save, so staff never has to see or set that field - which admin
page they're on already says it.

The add/edit form itself is split into what a challenge cannot work
without - label, slug, XP value, target, and which game(s) count - shown
right at the top with no fieldset heading, versus everything else
(description, active/checklist toggles, ordering, link, icon), which has a
sensible default and lives in a single collapsed "More options" section so
the common case is a five-field form.
"""

from django import forms
from django.contrib import admin

from xp.models import XPAction
from .models import DailyChallenge, SpecialChallenge, WeeklyChallenge

REQUIRED_FIELDS = ['label', 'slug', 'xp_value', 'challenge_target_count', 'challenge_source_actions']
OPTIONAL_FIELDS = ['description', 'is_active', 'is_daily_checklist', 'display_order', 'action_url', 'icon']


class _ChallengeFormBase(forms.ModelForm):
    """
    Forces challenge_period to the value implied by which admin page the
    staff member is on - set in __init__, BEFORE Django validates the form,
    not in ModelAdmin.save_model (which only runs after validation).
    XPAction.clean() checks challenge_period against
    event_starts_at/event_ends_at, so a Special Challenge submitted with
    dates would otherwise fail validation against the model's default
    'daily' period on a brand-new (unsaved) instance.

    Also seeds "Show on daily challenges" to checked by default for a new
    challenge - the model's own default is off (it's shared with background
    actions like gameplay_round that must never appear on a player
    checklist), but anything created through this dedicated UI is, by
    definition, meant to be seen - and makes target/source actually
    required here, even though XPAction itself allows either blank (it's
    shared with plain non-challenge rows, e.g. daily_login, via the general
    XP Actions admin): a challenge with no target or no source can never
    resolve or be discovered, so silently allowing that to be saved would
    just produce a broken, inert challenge.
    """
    period = None  # set on each concrete subclass below

    def __init__(self, *args, **kwargs):
        creating = kwargs.get('instance') is None or kwargs['instance'].pk is None
        if creating:
            kwargs.setdefault('initial', {})
            kwargs['initial'].setdefault('is_daily_checklist', True)
        super().__init__(*args, **kwargs)
        self.instance.challenge_period = self.period
        self.fields['challenge_target_count'].required = True
        self.fields['challenge_source_actions'].required = True


class DailyChallengeForm(_ChallengeFormBase):
    period = XPAction.PERIOD_DAILY

    class Meta:
        model = DailyChallenge
        fields = REQUIRED_FIELDS + OPTIONAL_FIELDS


class WeeklyChallengeForm(_ChallengeFormBase):
    period = XPAction.PERIOD_WEEKLY

    class Meta:
        model = WeeklyChallenge
        fields = REQUIRED_FIELDS + OPTIONAL_FIELDS


class SpecialChallengeForm(_ChallengeFormBase):
    period = XPAction.PERIOD_EVENT

    class Meta:
        model = SpecialChallenge
        fields = REQUIRED_FIELDS + ['event_starts_at', 'event_ends_at'] + OPTIONAL_FIELDS


class _ChallengeAdminBase(admin.ModelAdmin):
    list_display = (
        'slug', 'label', 'xp_value', 'challenge_target_count', 'source_actions_display',
        'is_active', 'is_daily_checklist', 'display_order', 'updated_at',
    )
    list_filter = ('is_active', 'is_daily_checklist')
    list_editable = ('xp_value', 'is_active', 'display_order')
    search_fields = ('slug', 'label')
    ordering = ('display_order', 'slug')
    # One less thing to type - the slug only has to be a unique identifier,
    # nothing reads it by convention the way a per-game round counter's
    # slug must (see xp/admin.py's Challenge fieldset for that one case
    # where the exact string does matter).
    prepopulated_fields = {'slug': ('label',)}
    # The actual "pick as many games as you like" control - a dual-list
    # checkbox picker rather than the default multi-select box.
    filter_horizontal = ('challenge_source_actions',)

    @admin.display(description='Source action(s)')
    def source_actions_display(self, obj):
        slugs = list(obj.challenge_source_actions.values_list('slug', flat=True))
        return ', '.join(slugs) if slugs else '—'


TARGET_DESCRIPTION = (
    'Tick which game(s) count: tick just one per-game round counter (e.g. '
    '"Plinko Rounds") to scope this to that game only, tick several to '
    'cover several games, or tick the single shared "Gameplay Round" '
    'action to count every game.'
)
MORE_OPTIONS_FIELDSET = ('More options', {
    'fields': tuple(OPTIONAL_FIELDS),
    'classes': ('collapse',),
    'description': (
        'Everything here has a sensible default - open this only if you '
        'need to: write a description, pause the challenge without '
        'deleting it, hide it from the player checklist, change its sort '
        'position among other challenges, or set the link/icon its tile '
        'uses.'
    ),
})


@admin.register(DailyChallenge)
class DailyChallengeAdmin(_ChallengeAdminBase):
    form = DailyChallengeForm
    fieldsets = (
        (None, {
            'fields': ('label', 'slug', 'xp_value', 'challenge_target_count', 'challenge_source_actions'),
            'description': f'Resets every day at local midnight. {TARGET_DESCRIPTION}',
        }),
        MORE_OPTIONS_FIELDSET,
    )


@admin.register(WeeklyChallenge)
class WeeklyChallengeAdmin(_ChallengeAdminBase):
    form = WeeklyChallengeForm
    fieldsets = (
        (None, {
            'fields': ('label', 'slug', 'xp_value', 'challenge_target_count', 'challenge_source_actions'),
            'description': f'Resets every Monday at local midnight. {TARGET_DESCRIPTION}',
        }),
        MORE_OPTIONS_FIELDSET,
    )


@admin.register(SpecialChallenge)
class SpecialChallengeAdmin(_ChallengeAdminBase):
    form = SpecialChallengeForm
    list_display = _ChallengeAdminBase.list_display + ('event_starts_at', 'event_ends_at')
    fieldsets = (
        (None, {
            'fields': (
                'label', 'slug', 'xp_value', 'challenge_target_count', 'challenge_source_actions',
                'event_starts_at', 'event_ends_at',
            ),
            'description': (
                f'{TARGET_DESCRIPTION} Runs exactly once, between the two '
                'dates - invisible and unearnable outside that window, and '
                'never repeats. Both dates are required.'
            ),
        }),
        MORE_OPTIONS_FIELDSET,
    )
