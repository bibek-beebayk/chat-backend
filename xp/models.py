import hashlib
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .ranks import invalidate_tier_cache


def tier_badge_upload_to(instance, filename):
    ext = (filename.rsplit('.', 1)[-1] if '.' in filename else 'png').lower()
    return f'tier_badges/{instance.slug}.{ext}'


def todays_rotation_pool_ids(pool, *, count, date_key):
    """
    Pure, deterministic daily-rotation selection: which `count` ids out of
    `pool` (an iterable of (id, slug) pairs) are "live" for `date_key` (an
    ISO date string, e.g. '2026-09-04'). Ranks the whole pool by a stable
    hash of (date_key, slug) and takes the first `count` - not
    random.seed(), so the result is reproducible across every server
    process and every Python version without needing a scheduled task or a
    stored "today's picks" row: every request that day, everywhere,
    recomputes the identical answer from nothing but the pool + the date +
    the count. The set changes automatically at local midnight (a new
    date_key) and whenever the pool's membership changes.

    count >= len(pool) simply returns the whole pool (no rotation effect,
    matches "0 disables rotation entirely" at the other extreme). Returns
    a set of ids - membership-tested, order doesn't matter to callers.
    """
    ranked = sorted(pool, key=lambda row: hashlib.sha256(f'{date_key}:{row[1]}'.encode()).hexdigest())
    return {row[0] for row in ranked[:count]}


class Tier(models.Model):
    """
    One rank tier in the Rollin Levels ladder. The whole ladder - names, XP
    thresholds, rank-up bonuses, flavor copy and badge artwork - is data here,
    fully managed from Django admin, not code. xp.ranks reads these rows (with
    a short-lived cache) for all rank math, and xp.views.rank_tiers_view serves
    them to the frontend.

    Only min_xp is stored for the range: each tier runs from its own min_xp up
    to (the next active tier's min_xp - 1), so ranges can never gap or overlap.
    Exactly one tier must have min_xp=0 so every XP total resolves to a tier.
    """
    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=60)
    min_xp = models.PositiveIntegerField(
        unique=True,
        help_text='Inclusive XP needed to reach this tier. Exactly one tier must be 0.',
    )
    rank_up_bonus_rp = models.PositiveIntegerField(
        default=0,
        help_text='One-time RP credited the first time a player reaches this tier. 0 = no bonus (e.g. the starting tier).',
    )
    tagline = models.CharField(max_length=120, blank=True)
    badge = models.ImageField(upload_to=tier_badge_upload_to, blank=True, null=True)
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive tiers are excluded from the ladder and all rank math.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['min_xp']

    def __str__(self):
        return f'{self.name} ({self.min_xp}+ XP)'

    @property
    def label(self):
        """Alias so a Tier stands in wherever the rank helpers' .label is read."""
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        invalidate_tier_cache()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        invalidate_tier_cache()


class XPAction(models.Model):
    slug = models.SlugField(max_length=64, unique=True)
    label = models.CharField(max_length=120)
    xp_value = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    max_awards_per_day = models.PositiveIntegerField(blank=True, null=True)
    # Minimal "challenge" support (see xp/services.py) - when a target and at
    # least one source action are set, this action can only be awarded once
    # at least challenge_target_count EARN entries across ALL of
    # challenge_source_actions exist within the current window (see
    # challenge_window() below). Multiple sources is what lets a challenge
    # be scoped to specific games: pick a game's own round counter (e.g.
    # "Plinko Rounds") to count only that game, several to count several
    # games, or the shared "Gameplay Round" action alone to count every
    # game - see each game's xp_hooks.py for what it fires every round.
    challenge_target_count = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text='How many of the source action(s) are needed. Set with Challenge source action(s).',
    )
    challenge_source_actions = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='challenge_dependents',
        help_text=(
            'The action(s) being counted, e.g. pick "Plinko Rounds" alone to '
            'scope this challenge to just Plinko, several per-game counters '
            'to cover several games, or "Gameplay Round" alone to count '
            'every game.'
        ),
    )

    # How often the target/source count above resets, i.e. which window of
    # time counts. Only meaningful alongside challenge_target_count/
    # challenge_source_actions - see challenge_window() for the actual date
    # math this drives, which xp.services.award_xp() and
    # xp.views.daily_progress_view both read rather than each assuming a
    # calendar day the way this used to be hardcoded everywhere.
    PERIOD_DAILY = 'daily'
    PERIOD_WEEKLY = 'weekly'
    PERIOD_EVENT = 'event'
    CHALLENGE_PERIOD_CHOICES = [
        (PERIOD_DAILY, 'Daily - resets at midnight'),
        (PERIOD_WEEKLY, 'Weekly - resets Monday'),
        (PERIOD_EVENT, 'Event - runs once, between the two dates below'),
    ]
    challenge_period = models.CharField(
        max_length=8,
        choices=CHALLENGE_PERIOD_CHOICES,
        default=PERIOD_DAILY,
        help_text='How often the challenge target resets. "Event" needs the two dates below; the other two ignore them.',
    )
    event_starts_at = models.DateTimeField(
        blank=True, null=True,
        help_text='Event period only - the challenge is invisible and cannot be earned before this.',
    )
    event_ends_at = models.DateTimeField(
        blank=True, null=True,
        help_text='Event period only - the challenge is invisible and cannot be earned after this.',
    )
    # Opt-in daily rotation: a Daily-period challenge with this set is only
    # actually live on some days, not every day - which days is decided by
    # todays_rotation_pool_ids() below, not stored anywhere, so it needs no
    # scheduled task and is identical across every server process. Only
    # meaningful for challenge_period == PERIOD_DAILY - see clean(). The
    # player-facing "how many are live today" knob is
    # challenges.models.DailyRotationConfig, a singleton staff edits in the
    # "Challenges" admin section.
    rotation_pool = models.BooleanField(
        default=False,
        help_text=(
            'Daily challenges only. When on, this challenge is only live '
            'on some days (a random subset of the whole rotation pool, '
            'sized by Daily Rotation Settings) rather than every day - '
            'build a larger pool of these than the daily count and a '
            'different subset shows each day.'
        ),
    )

    # --- Presentation ---
    # Everything below exists so a new challenge or achievement is a row in
    # this table and nothing else. Before these fields, the checklist and
    # achievement lists were hardcoded Python lists in xp/views.py and the
    # labels, icons and links were hardcoded slug maps in the frontend - so
    # each new challenge needed a code change and a deploy in two places.
    is_daily_checklist = models.BooleanField(
        default=False,
        help_text=(
            "Show this on the player's Daily Challenges checklist (the "
            '/challenges page, the home banner and the rewards page). Leave '
            'off for background actions players never see as a task, like '
            'qualified_gameplay.'
        ),
    )
    is_achievement = models.BooleanField(
        default=False,
        help_text='Show this as an achievement badge on player profiles.',
    )
    display_order = models.PositiveSmallIntegerField(
        default=100,
        help_text='Lower numbers appear first in both lists. Ties fall back to slug order.',
    )
    action_url = models.CharField(
        max_length=200,
        blank=True,
        help_text=(
            'Where the tile links to, e.g. "/games/hilo". Leave blank for '
            'something the player cannot act on directly (like Daily Login) '
            'and the tile renders without a link.'
        ),
    )
    icon = models.CharField(
        max_length=8,
        blank=True,
        help_text='Optional emoji shown on the tile, e.g. 🃏. Falls back to a suit glyph.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slug']

    def __str__(self):
        return f'{self.slug} (+{self.xp_value} XP)'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.challenge_period == self.PERIOD_EVENT:
            if not self.event_starts_at or not self.event_ends_at:
                raise ValidationError('Event challenges need both a start and an end date.')
            if self.event_ends_at <= self.event_starts_at:
                raise ValidationError('An event must end after it starts.')
        elif self.event_starts_at or self.event_ends_at:
            raise ValidationError('Start/end dates only apply to the Event period - clear them or set the period to Event.')

        if self.rotation_pool and self.challenge_period != self.PERIOD_DAILY:
            raise ValidationError('Rotation pool only applies to Daily challenges.')

    @property
    def display_label(self):
        """
        The label as players see it. `{target}` in the label is replaced with
        challenge_target_count, so "Play {target} Rounds" stays correct when
        the target is retuned in admin - previously the round count was
        interpolated in the frontend, which meant the admin-editable label
        was partly ignored.
        """
        if '{target}' not in self.label:
            return self.label
        return self.label.replace('{target}', str(self.challenge_target_count or 1))

    def challenge_window(self, *, now=None):
        """
        (start, end) the challenge's progress is counted within right now.
        `end` is None for daily/weekly - the count is simply "since start,
        with no upper bound yet" - and the explicit event_ends_at for an
        event. `start` can be None only for a misconfigured event (no
        event_starts_at set); callers treat that as never eligible via
        is_challenge_open() below, same as a not-yet-started event.

        This is the one place "which window of time counts" is computed -
        xp.services.award_xp()'s eligibility check and
        xp.views.daily_progress_view's progress display both call this
        rather than each hardcoding a date boundary, so they can never
        disagree with each other.
        """
        now = now or timezone.now()
        if self.challenge_period == self.PERIOD_EVENT:
            return self.event_starts_at, self.event_ends_at

        local_midnight = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        if self.challenge_period == self.PERIOD_WEEKLY:
            local_midnight -= timedelta(days=local_midnight.weekday())  # back to Monday
        return local_midnight, None

    def challenge_period_key(self, *, now=None):
        """
        Identifies *which instance* of a recurring window we're in, so the
        award idempotency key changes when the window rolls over - a
        weekly challenge earned last week is earnable again this week.
        An event has exactly one instance ever, so its own id suffices.
        """
        if self.challenge_period == self.PERIOD_EVENT:
            return f'event-{self.pk}'
        start, _ = self.challenge_window(now=now)
        return start.date().isoformat() if start else 'unscheduled'

    def is_challenge_open(self, *, now=None):
        """
        Whether the challenge's window is open right now at all -
        independent of whether the target has been met. Also the single
        place daily rotation is enforced (see is_in_todays_rotation): both
        xp.services.award_xp()'s eligibility check and
        xp.views.daily_progress_view's display call this one method, so a
        challenge left out of today's rotation can neither be earned nor
        shown - never just hidden while still secretly progressing.
        """
        now = now or timezone.now()
        start, end = self.challenge_window(now=now)
        if start is not None and now < start:
            return False
        if end is not None and now > end:
            return False
        if self.rotation_pool and not self.is_in_todays_rotation(now=now):
            return False
        return True

    def is_in_todays_rotation(self, *, now=None):
        """
        Only meaningful when rotation_pool=True (non-pool challenges have
        nothing to check and always return True). Queries the sibling pool
        - every other active rotation_pool challenge - and defers the
        actual selection to the pure, unit-testable
        todays_rotation_pool_ids() below.

        Lazy-imports challenges.models to avoid a circular import at
        module load time: challenges/models.py imports XPAction from here
        at its own module level (for the Daily/Weekly/Special proxy
        models), so the reverse import can only safely happen inside a
        function body, once both modules have already finished loading -
        mirrors the lazy cross-app imports already used elsewhere in this
        codebase (e.g. points.services._grant_round_xp).
        """
        if not self.rotation_pool:
            return True

        from challenges.models import DailyRotationConfig

        now = now or timezone.now()
        date_key = timezone.localtime(now).date().isoformat()
        count = DailyRotationConfig.get_solo().active_count
        # XPAction (not type(self)/self.__class__) deliberately - a proxy
        # subclass's own manager (e.g. DailyChallenge's) is scoped to a
        # single period and to challenges only, which would silently
        # exclude part of the pool if this were ever called on a proxy
        # instance instead of a plain XPAction one.
        pool = XPAction.objects.filter(rotation_pool=True, is_active=True).values_list('id', 'slug')
        selected_ids = todays_rotation_pool_ids(pool, count=count, date_key=date_key)
        return self.id in selected_ids

    def challenge_resets_at(self, *, now=None):
        """
        When this window's progress next resets (daily/weekly) or closes
        for good (event, or None if no end date is set). Display-only - a
        countdown, not used in any eligibility math - so a frontend can
        show "resets in 4h" / "ends in 3d" without knowing which period
        type it's looking at.
        """
        if self.challenge_period == self.PERIOD_EVENT:
            return self.event_ends_at
        start, _ = self.challenge_window(now=now)
        if self.challenge_period == self.PERIOD_WEEKLY:
            return start + timedelta(days=7)
        return start + timedelta(days=1)


class XPBalance(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='xp_balance',
    )
    total_xp = models.PositiveIntegerField(default=0)
    # Cached, not authoritative - always re-derived from total_xp via
    # xp.ranks.rank_for_xp() inside award_xp(), never hand-set elsewhere
    # (treat like PointsBalance.balance: read-only in admin). Exists so
    # reads don't need to recompute rank from total_xp every time, and so
    # rank-up detection has an "old value" to diff against.
    rank_slug = models.CharField(max_length=32, blank=True, default='')
    rank_updated_at = models.DateTimeField(blank=True, null=True)
    # Set to a rank slug the moment a rank-up happens (see
    # xp.services._apply_rank_up_bonus), cleared back to '' once the
    # frontend has shown the "Level Up!" celebration and called
    # /api/xp/acknowledge-level-up/. Empty means "nothing to celebrate".
    pending_celebration_rank = models.CharField(max_length=32, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-total_xp']

    def __str__(self):
        return f'{self.user} XP: {self.total_xp} ({self.rank_slug})'


class XPLedgerEntry(models.Model):
    ENTRY_EARN = 'earn'
    ENTRY_ADJUSTMENT = 'adjustment'
    ENTRY_TYPE_CHOICES = [
        (ENTRY_EARN, 'Earn'),
        (ENTRY_ADJUSTMENT, 'Adjustment'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='xp_ledger_entries',
    )
    entry_type = models.CharField(max_length=24, choices=ENTRY_TYPE_CHOICES, default=ENTRY_EARN)
    delta = models.IntegerField()
    xp_after = models.PositiveIntegerField()
    rank_after = models.CharField(max_length=32, blank=True)
    action = models.ForeignKey(
        XPAction,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ledger_entries',
    )
    idempotency_key = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    awarded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='xp_awarded_entries',
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'action', 'idempotency_key'],
                condition=~Q(idempotency_key=''),
                name='unique_xp_earn_idempotency_key',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['action', 'created_at']),
        ]

    def __str__(self):
        sign = '+' if self.delta >= 0 else ''
        return f'{self.user} {self.entry_type} {sign}{self.delta} XP'
