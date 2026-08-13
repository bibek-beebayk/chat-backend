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
    balance = models.PositiveIntegerField(default=0)
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
    delta = models.IntegerField()
    balance_after = models.PositiveIntegerField()
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
        return f'{self.user} {self.entry_type} {self.delta:+d}'


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
