from django.conf import settings
from django.db import models
from django.db.models import Q

from .constants import GAME_VERSION, RANKS, SUITS

RANK_CHOICES = [(rank, rank) for rank in RANKS]
SUIT_CHOICES = [(suit, suit.capitalize()) for suit in SUITS]


class HiLoRound(models.Model):
    """
    One Hi-Lo round: a wager, a face-up card, and an accumulated multiplier
    that climbs across any number of predictions until the player busts or
    cashes out.

    Unlike RocketRound there is no time dimension - a round's state only ever
    changes when the player acts, so nothing needs lazy resolution against
    elapsed seconds. The concurrency shape is otherwise identical to Rocket's
    (one active round per user at the DB level, client_request_id replay
    protection, both ledger legs recorded).
    """

    STATUS_ACTIVE = 'active'
    STATUS_CASHED_OUT = 'cashed_out'
    STATUS_BUSTED = 'busted'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_CASHED_OUT, 'Cashed Out'),
        (STATUS_BUSTED, 'Busted'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='hilo_rounds',
    )
    game = models.ForeignKey(
        'games.Game',
        on_delete=models.PROTECT,
        related_name='hilo_rounds',
    )
    # Recorded per-round (not read from constants at display time) so a
    # future edge/odds change can never alter what an old round is
    # understood to mean - mirrors RocketRound/SlotRound.
    game_version = models.CharField(max_length=32, default=GAME_VERSION)

    wager_amount = models.DecimalField(max_digits=12, decimal_places=2)

    # The face-up card the next prediction is made against. Advanced on both
    # a win and a push (a push is not a loss - the player continues from the
    # new card with an unchanged multiplier).
    current_rank = models.CharField(max_length=2, choices=RANK_CHOICES)
    current_suit = models.CharField(max_length=8, choices=SUIT_CHOICES)

    # Accumulated across every winning prediction, clamped to
    # constants.MAX_MULTIPLIER. Starts at 1.00 - a round cashed out before
    # any correct prediction would just return the wager, which is why
    # services.cash_out requires multiplier > 1.00.
    multiplier = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    # Consecutive correct predictions. Pushes neither increment nor reset it.
    # Read directly by xp_hooks - unlike Rocket's "Five Alive", which had to
    # walk round history, the streak here is a field on the round already.
    streak = models.PositiveSmallIntegerField(default=0)
    # Monotonic count of resolved predictions. Doubles as the round's
    # anti-double-predict token: a predict request must name the step index
    # it believes it is acting on, so a duplicate click or a network retry
    # arrives stale and replays state instead of drawing a second card.
    # See services.predict.
    steps_taken = models.PositiveSmallIntegerField(default=0)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    # True when the round was force-settled by the server because it hit
    # MAX_MULTIPLIER / MAX_PAYOUT / MAX_STEPS rather than by an explicit
    # player cash-out. Presentation uses it for the jackpot animation.
    capped = models.BooleanField(default=False)
    payout_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Reflects the balance right after the initial debit at play time;
    # updated again on a cash-out to reflect the post-credit balance. Left
    # unchanged on a bust (no further balance movement).
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    debit_ledger_entry = models.ForeignKey(
        'points.PointsLedgerEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hilo_round_debits',
    )
    credit_ledger_entry = models.ForeignKey(
        'points.PointsLedgerEntry',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hilo_round_credits',
    )

    # Optional client-supplied key so a double-click/network-retry replays
    # the same round instead of starting (and charging) a second one.
    client_request_id = models.CharField(max_length=64, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'created_at'])]
        constraints = [
            # At most one in-flight round per user - a DB-level guard
            # against "start two rounds at once" races, immune to request
            # timing regardless of application-layer locking. Same pattern
            # as RocketRound.
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(status='active'),
                name='unique_active_hilo_round_per_user',
            ),
            models.UniqueConstraint(
                fields=['user', 'client_request_id'],
                condition=~Q(client_request_id=''),
                name='unique_hilo_client_request_id',
            ),
        ]

    def __str__(self):
        return f'{self.user} hi-lo {self.wager_amount} x{self.multiplier} ({self.status})'


class HiLoStep(models.Model):
    """
    One prediction within a round, recorded whatever the outcome.

    This is what makes the design spec's stats panel (s19) and recent-round
    history table (s20) queries over data that already exists rather than
    new aggregation, and it is the audit trail for every card the server
    ever generated in a round.
    """

    OUTCOME_WIN = 'win'
    OUTCOME_PUSH = 'push'
    OUTCOME_LOSS = 'loss'
    OUTCOME_CHOICES = [
        (OUTCOME_WIN, 'Win'),
        (OUTCOME_PUSH, 'Push'),
        (OUTCOME_LOSS, 'Loss'),
    ]

    PREDICTION_HIGHER = 'higher'
    PREDICTION_LOWER = 'lower'
    PREDICTION_CHOICES = [
        (PREDICTION_HIGHER, 'Higher'),
        (PREDICTION_LOWER, 'Lower'),
    ]

    round = models.ForeignKey(HiLoRound, on_delete=models.CASCADE, related_name='steps')
    # 0-based, equal to the round's steps_taken at the moment the prediction
    # was accepted. The unique_together below makes a duplicate write for
    # the same step impossible at the database level, independent of any
    # application-layer check.
    step_index = models.PositiveSmallIntegerField()

    from_rank = models.CharField(max_length=2, choices=RANK_CHOICES)
    from_suit = models.CharField(max_length=8, choices=SUIT_CHOICES)
    prediction = models.CharField(max_length=6, choices=PREDICTION_CHOICES)
    to_rank = models.CharField(max_length=2, choices=RANK_CHOICES)
    to_suit = models.CharField(max_length=8, choices=SUIT_CHOICES)
    outcome = models.CharField(max_length=4, choices=OUTCOME_CHOICES)

    # The quoted multiplier for this prediction (1.00 for a push, which
    # leaves the accumulated multiplier untouched), and the round's
    # accumulated multiplier after applying it.
    step_multiplier = models.DecimalField(max_digits=8, decimal_places=2)
    multiplier_after = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['round_id', 'step_index']
        unique_together = ('round', 'step_index')

    def __str__(self):
        return f'round={self.round_id} #{self.step_index} {self.from_rank}->{self.to_rank} {self.outcome}'
