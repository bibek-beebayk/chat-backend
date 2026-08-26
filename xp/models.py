from django.conf import settings
from django.db import models
from django.db.models import Q


class XPAction(models.Model):
    slug = models.SlugField(max_length=64, unique=True)
    label = models.CharField(max_length=120)
    xp_value = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    max_awards_per_day = models.PositiveIntegerField(blank=True, null=True)
    # Minimal "daily challenge" support (see xp/services.py) - when both are
    # set, this action can only be awarded once at least
    # challenge_target_count EARN entries for challenge_source_action exist
    # today. Avoids a separate Challenge model for the one challenge type
    # buildable with this pass's infrastructure ("complete N qualified
    # gameplay rounds today").
    challenge_target_count = models.PositiveIntegerField(blank=True, null=True)
    challenge_source_action = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='challenge_dependents',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slug']

    def __str__(self):
        return f'{self.slug} (+{self.xp_value} XP)'


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
