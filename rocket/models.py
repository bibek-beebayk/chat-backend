from django.conf import settings
from django.db import models
from django.db.models import Q
from .constants import GAME_VERSION


class RocketRound(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_CASHED_OUT = 'cashed_out'
    STATUS_CRASHED = 'crashed'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_CASHED_OUT, 'Cashed Out'),
        (STATUS_CRASHED, 'Crashed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='rocket_rounds',
    )
    game = models.ForeignKey(
        'games.Game',
        on_delete=models.PROTECT,
        related_name='rocket_rounds',
    )
    # Recorded per-round (not just read from constants.GAME_VERSION at
    # display time) so a future curve/distribution change can never alter
    # what an old round is understood to mean - mirrors slots.SlotRound.
    game_version = models.CharField(max_length=32, default=GAME_VERSION)

    wager_amount = models.DecimalField(max_digits=12, decimal_places=2)
    auto_cashout_multiplier = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    # The server-generated outcome - NEVER exposed to the client while
    # status=active (see rocket/serializers.py). This is the single
    # source of truth every cashout/crash decision is checked against.
    crash_point = models.DecimalField(max_digits=8, decimal_places=2)
    # When the multiplier actually starts climbing (created_at +
    # COUNTDOWN_SECONDS). Elapsed time is always computed against this,
    # both for the pre-launch countdown display (elapsed <= 0) and the
    # running multiplier - see rocket/services.py::multiplier_at_elapsed.
    started_at = models.DateTimeField()

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    # Set only once the round resolves - the multiplier the player actually
    # cashed out at (may differ from crash_point, which stays hidden even
    # after a cashout since the rocket's "true" crash point is never
    # reached in that case).
    cashout_multiplier = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    payout_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Reflects the balance right after the initial debit at play time;
    # updated again on a successful cash-out to reflect the post-credit
    # balance. Left unchanged on a crash (no further balance movement).
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    debit_ledger_entry = models.ForeignKey(
        'points.PointsLedgerEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rocket_round_debits',
    )
    credit_ledger_entry = models.ForeignKey(
        'points.PointsLedgerEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rocket_round_credits',
    )

    # Optional client-supplied key so a double-click/network-retry replays
    # the same round instead of placing (and charging) a second one - see
    # the unique constraint below and rocket.services.place_bet.
    client_request_id = models.CharField(max_length=64, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'created_at'])]
        constraints = [
            # At most one in-flight round per user at a time - a DB-level
            # guard against "place two bets at once" races, immune to
            # request timing regardless of application-layer locking.
            # Mirrors points.PointsRedemptionRequest's identical
            # one-active-thing-per-user pattern.
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(status='active'),
                name='unique_active_rocket_round_per_user',
            ),
            models.UniqueConstraint(
                fields=['user', 'client_request_id'],
                condition=~Q(client_request_id=''),
                name='unique_rocket_client_request_id',
            ),
        ]

    def __str__(self):
        return f'{self.user} rocket play {self.wager_amount} ({self.status})'
