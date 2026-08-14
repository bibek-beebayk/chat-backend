from django.conf import settings
from django.db import models
from django.db.models import Q
from .constants import GAME_VERSION


class SlotRound(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='slot_rounds',
    )
    game = models.ForeignKey(
        'games.Game',
        on_delete=models.PROTECT,
        related_name='slot_rounds',
    )
    # Recorded per-round (not just read from constants.GAME_VERSION at
    # display time) so a future slot_v2 reel/paytable change can never alter
    # what an old round is understood to mean.
    game_version = models.CharField(max_length=32, default=GAME_VERSION)
    wager_amount = models.PositiveIntegerField()
    reel_1_stop = models.PositiveSmallIntegerField()
    reel_2_stop = models.PositiveSmallIntegerField()
    reel_3_stop = models.PositiveSmallIntegerField()
    # grid_snapshot[reel][row] = symbol id, derived from the 3 stops above -
    # stored redundantly (rather than recomputed from stops on read) so the
    # round stays reproducible even if REEL_STRIPS is edited later.
    grid_snapshot = models.JSONField()
    # List of {line_index, symbol, multiplier, payout} for winning lines only.
    winning_lines = models.JSONField(default=list)
    total_multiplier = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    payout_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_result = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    ledger_entry = models.OneToOneField(
        'points.PointsLedgerEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='slot_round',
    )
    # Optional client-supplied key so a double-click/network-retry replays
    # the same settled round instead of spinning (and charging) twice - see
    # the unique constraint below and slots.services.play_round.
    client_request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'created_at'])]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'client_request_id'],
                condition=~Q(client_request_id=''),
                name='unique_slot_client_request_id',
            ),
        ]

    def __str__(self):
        return f'{self.user} slot spin {self.wager_amount} -> {self.payout_amount} ({self.game_version})'
