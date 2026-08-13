from django.conf import settings
from django.db import models
from .constants import RISK_CHOICES, ROWS_CHOICES


class PlinkoRound(models.Model):
    ROWS_CHOICES = [(value, str(value)) for value in ROWS_CHOICES]
    RISK_CHOICES = [(value, value.capitalize()) for value in RISK_CHOICES]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='plinko_rounds',
    )
    game = models.ForeignKey(
        'games.Game',
        on_delete=models.PROTECT,
        related_name='plinko_rounds',
    )
    rows = models.PositiveSmallIntegerField(choices=ROWS_CHOICES)
    risk_level = models.CharField(max_length=8, choices=RISK_CHOICES)
    wager_amount = models.PositiveIntegerField()
    slot_index = models.PositiveSmallIntegerField()
    multiplier = models.DecimalField(max_digits=8, decimal_places=2)
    payout_amount = models.DecimalField(max_digits=12, decimal_places=2)
    path = models.JSONField()
    drop_offset = models.FloatField(default=0.0)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    ledger_entry = models.OneToOneField(
        'points.PointsLedgerEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='plinko_round',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f'{self.user} plinko {self.rows}r/{self.risk_level} slot={self.slot_index} x{self.multiplier}'
