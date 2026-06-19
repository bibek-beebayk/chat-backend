from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


STREAK_TARGET_DAYS = 7
STREAK_REWARD_AMOUNT = Decimal('5.00')


class LoginStreak(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='login_streak',
    )
    current_streak = models.PositiveIntegerField(default=0)
    last_login_date = models.DateField(blank=True, null=True)
    receivable_bonus = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    last_awarded_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.user} streak: {self.current_streak}'

    @property
    def is_reward_available(self):
        return self.receivable_bonus >= STREAK_REWARD_AMOUNT

    @property
    def days_remaining(self):
        return max(0, STREAK_TARGET_DAYS - self.current_streak)


class LoginStreakEntry(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='login_streak_entries',
    )
    login_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'login_date'], name='unique_login_streak_entry_per_day'),
        ]
        ordering = ['-login_date', '-created_at']
        verbose_name = 'Login streak entry'
        verbose_name_plural = 'Login streak entries'

    def __str__(self):
        return f'{self.user} visit on {self.login_date}'


class StreakRedemptionRequest(models.Model):
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
        related_name='streak_redemption_requests',
    )
    amount = models.DecimalField(max_digits=8, decimal_places=2, default=STREAK_REWARD_AMOUNT)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    note = models.TextField(blank=True)
    staff_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_streak_redemptions',
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
                name='unique_active_streak_redemption_per_user',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f'{self.user} redemption {self.amount} ({self.status})'

    def mark_reviewed(self, staff_user, status_value, staff_note=''):
        self.status = status_value
        self.reviewed_by = staff_user
        self.reviewed_at = timezone.now()
        if staff_note:
            self.staff_note = staff_note
        if status_value == self.STATUS_COMPLETED:
            self.completed_at = timezone.now()
