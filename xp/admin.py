from django.contrib import admin
from django.utils.html import format_html
from .models import Tier, XPAction, XPBalance, XPLedgerEntry


@admin.register(Tier)
class TierAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'min_xp', 'rank_up_bonus_rp', 'is_active', 'badge_preview', 'updated_at')
    list_editable = ('min_xp', 'rank_up_bonus_rp', 'is_active')
    ordering = ('min_xp',)
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('badge_preview', 'created_at', 'updated_at')
    fields = ('name', 'slug', 'min_xp', 'rank_up_bonus_rp', 'tagline', 'badge', 'badge_preview', 'is_active', 'created_at', 'updated_at')

    @admin.display(description='Badge')
    def badge_preview(self, obj):
        if obj.badge:
            return format_html('<img src="{}" style="height:48px;width:48px;object-fit:contain;" />', obj.badge.url)
        return '—'


@admin.register(XPAction)
class XPActionAdmin(admin.ModelAdmin):
    """
    The whole challenge/achievement system is configured here. Adding a
    challenge - daily, weekly, or a time-boxed event, scoped to one game,
    several, or every game - is: create (or pick) an action, tick "Show on
    daily challenges", set the target, tick which source action(s) count,
    and the period, and save. Nothing else - the API serves it and every
    player-facing surface renders it from these fields.

    The one thing admin cannot create is a brand-new *signal*. An action is
    only ever awarded by server code calling xp.services.award_xp() (or,
    for a challenge, xp.services.award_matching_challenges() - see its
    docstring) with its slug, so a challenge must count something the
    games already emit - see the "Challenge" fieldset's help text for the
    list of what's available per game.
    """

    list_display = (
        'slug', 'label', 'xp_value', 'is_active',
        'is_daily_checklist', 'is_achievement', 'display_order',
        'challenge_period', 'challenge_target_count', 'source_actions_display', 'updated_at',
    )
    list_filter = ('is_active', 'is_daily_checklist', 'is_achievement', 'challenge_period')
    list_editable = ('xp_value', 'is_active', 'is_daily_checklist', 'is_achievement', 'display_order')
    search_fields = ('slug', 'label')
    ordering = ('display_order', 'slug')
    # A proper dual-list checkbox picker for the source-actions m2m, rather
    # than the default multi-select box - this is the actual "pick as many
    # games as you like" control.
    filter_horizontal = ('challenge_source_actions',)

    @admin.display(description='Source action(s)')
    def source_actions_display(self, obj):
        slugs = list(obj.challenge_source_actions.values_list('slug', flat=True))
        return ', '.join(slugs) if slugs else '—'

    fieldsets = (
        (None, {
            'fields': ('slug', 'label', 'description', 'xp_value', 'is_active'),
            'description': (
                'The slug is what server code awards against and cannot be '
                'renamed safely once in use. Put {target} in the label to '
                'have the challenge target substituted in, e.g. '
                '"Play {target} Rounds".'
            ),
        }),
        ('Limits', {
            'fields': ('max_awards_per_day',),
            'description': 'Blank means unlimited awards per day. Unrelated to the challenge period below - this caps how often the action itself can be awarded, e.g. a streak achievement capped at 3/day.',
        }),
        ('Challenge', {
            'fields': (
                'challenge_target_count', 'challenge_source_actions', 'challenge_period',
                'event_starts_at', 'event_ends_at', 'rotation_pool',
            ),
            'description': (
                'Set a target and tick one or more source actions to make '
                'this a challenge: it is only awarded once the player has '
                'earned <em>target</em> across ALL of the ticked source '
                'actions combined, within the current window. '
                '<strong>Which games count is decided entirely by which '
                'source actions you tick</strong> - tick just '
                '<code>plinko_gameplay_round</code> to scope this to Plinko '
                'only, tick that plus <code>rocket_gameplay_round</code> to '
                'count Plinko and Rocket together, or tick the single '
                'shared <code>gameplay_round</code> action to count every '
                'game (that\'s what the default "Play N Rounds" challenge '
                'does). Per-game round counters exist for '
                '<code>plinko_gameplay_round</code>, '
                '<code>rocket_gameplay_round</code>, '
                '<code>hilo_gameplay_round</code>, and '
                '<code>slots_gameplay_round</code>. Other per-game signals '
                'like <code>hilo_streak_5</code> or '
                '<code>rocket_cashout_above_5x</code> also work as sources '
                'for a more specific challenge. <strong>Daily</strong> '
                'resets at local midnight, <strong>Weekly</strong> resets '
                'Monday, and <strong>Event</strong> runs exactly once '
                'between the two dates below - invisible and unearnable '
                'outside that window, and never repeats. <strong>Rotation '
                'pool</strong> (Daily or Weekly only) makes this challenge '
                'show on only some days or weeks instead of every one - '
                'build a larger pool of these than the configured count in '
                'Rotation Settings (under Challenges in the sidebar) and a '
                'different subset goes live each period. No further setup '
                'needed after saving - the next qualifying round from any '
                'ticked game picks it up automatically (see '
                'xp.services.award_matching_challenges).'
            ),
        }),
        ('Display', {
            'fields': ('is_daily_checklist', 'is_achievement', 'display_order', 'action_url', 'icon'),
            'description': (
                'Controls whether and how players see this. Leave both '
                'checkboxes off for background actions that should earn XP '
                'without appearing as a task.'
            ),
        }),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
    readonly_fields = ('created_at', 'updated_at')


@admin.register(XPBalance)
class XPBalanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'total_xp', 'rank_slug', 'rank_updated_at', 'updated_at')
    list_filter = ('rank_slug',)
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('total_xp', 'rank_slug', 'rank_updated_at', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(XPLedgerEntry)
class XPLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('user', 'entry_type', 'delta', 'xp_after', 'rank_after', 'action', 'created_at')
    list_filter = ('entry_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'idempotency_key', 'note')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
