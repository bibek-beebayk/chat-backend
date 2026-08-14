from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class PointAction(models.Model):
    slug = models.SlugField(max_length=64, unique=True)
    label = models.CharField(max_length=120)
    points_value = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    max_awards_per_day = models.PositiveIntegerField(blank=True, null=True)
    # Defaults True so ordinary earn actions surface in the player-facing
    # "how to earn" info without extra setup - staff flip this off for
    # internal/one-off bookkeeping actions (e.g. a dated backfill run) that
    # would otherwise confuse players reading the Reward Points explainer.
    is_visible_to_players = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slug']

    def __str__(self):
        return f'{self.slug} (+{self.points_value})'


class PointsBalance(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='points_balance',
    )
    # Decimal (not PositiveIntegerField) so fractional payouts - e.g. a 10-point
    # Plinko wager at a 1.08x multiplier settling at 10.80 - persist exactly
    # instead of being rounded away. No Django PositiveDecimalField exists;
    # staying non-negative is enforced at the application layer (see
    # InsufficientPoints in points/services.py), matching the precedent set by
    # rewards.LoginStreak.receivable_bonus (also a plain DecimalField).
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    lifetime_earned = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.user} balance: {self.balance}'


class PointsAdjustment(PointsBalance):
    """Proxy of PointsBalance so the admin "Award / Deduct Points" page shows up as
    its own clickable entry in the admin nav, mirroring accounts.PlayerSearch."""

    class Meta:
        proxy = True
        verbose_name = 'Award / Deduct Points'
        verbose_name_plural = 'Award / Deduct Points'


class PointsLedgerEntry(models.Model):
    ENTRY_EARN = 'earn'
    ENTRY_REDEMPTION_HOLD = 'redemption_hold'
    ENTRY_REDEMPTION_REFUND = 'redemption_refund'
    ENTRY_REDEMPTION_FINALIZE = 'redemption_finalize'
    ENTRY_GAME_ROUND = 'game_round'
    ENTRY_ADJUSTMENT = 'adjustment'
    ENTRY_TYPE_CHOICES = [
        (ENTRY_EARN, 'Earn'),
        (ENTRY_REDEMPTION_HOLD, 'Redemption Hold'),
        (ENTRY_REDEMPTION_REFUND, 'Redemption Refund'),
        (ENTRY_REDEMPTION_FINALIZE, 'Redemption Finalize'),
        (ENTRY_GAME_ROUND, 'Game Round'),
        (ENTRY_ADJUSTMENT, 'Adjustment'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='points_ledger_entries',
    )
    entry_type = models.CharField(max_length=24, choices=ENTRY_TYPE_CHOICES)
    delta = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    action = models.ForeignKey(
        PointAction,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ledger_entries',
    )
    redemption_request = models.ForeignKey(
        'PointsRedemptionRequest',
        on_delete=models.SET_NULL,
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
        related_name='points_awarded_entries',
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'action', 'idempotency_key'],
                condition=~Q(idempotency_key=''),
                name='unique_points_earn_idempotency_key',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['entry_type', 'created_at']),
        ]

    def __str__(self):
        sign = '+' if self.delta >= 0 else ''
        return f'{self.user} {self.entry_type} {sign}{self.delta}'


class PointsRedemptionConfig(models.Model):
    """
    Singleton (always pk=1), admin-editable. Holds the redemption minimum
    and the Reward-Point-to-Hi-Rollin-Credit conversion rate - the doc
    explicitly leaves the rate unspecified rather than hard-coding an
    assumed value, so this is staff-configurable, and each redemption
    request snapshots the rate it was created under (see
    PointsRedemptionRequest.conversion_rate_snapshot) so later rate changes
    never alter historical requests.
    """
    min_redemption_points = models.PositiveIntegerField(default=5000)
    rp_to_credit_rate = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal('1.0000'))
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = 'Redemption Settings'
        verbose_name_plural = 'Redemption Settings'

    def __str__(self):
        return f'Redemption settings (min={self.min_redemption_points}, rate={self.rp_to_credit_rate})'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class PointsRedemptionRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_COMPLETED = 'completed'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_REJECTED, 'Rejected'),
    ]
    ACTIVE_STATUSES = [STATUS_PENDING, STATUS_APPROVED]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='points_redemption_requests',
    )
    points_amount = models.PositiveIntegerField()
    reward_description = models.CharField(max_length=255, blank=True)
    # Snapshot of PointsRedemptionConfig at creation time - nullable because
    # pre-existing rows (created before this field existed) have no
    # knowable historical rate; never backfilled with a guess.
    conversion_rate_snapshot = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    hi_rollin_credit_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    note = models.TextField(blank=True)
    staff_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_points_redemptions',
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(status__in=['pending', 'approved']),
                name='unique_active_points_redemption_per_user',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f'{self.user} redemption {self.points_amount} pts ({self.status})'

    def mark_reviewed(self, staff_user, status_value, staff_note=''):
        self.status = status_value
        self.reviewed_by = staff_user
        self.reviewed_at = timezone.now()
        if staff_note:
            self.staff_note = staff_note
        if status_value == self.STATUS_COMPLETED:
            self.completed_at = timezone.now()
