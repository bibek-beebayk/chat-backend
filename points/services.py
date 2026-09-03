from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.utils import timezone
from .models import PointAction, PointsBalance, PointsLedgerEntry, PointsRedemptionConfig, PointsRedemptionRequest


class InsufficientPoints(Exception):
    pass


class ActiveRedemptionExists(Exception):
    pass


class BelowMinimumRedemption(Exception):
    def __init__(self, minimum):
        self.minimum = minimum
        super().__init__(f'Minimum redemption is {minimum} points.')


class DailyCapExceeded(Exception):
    def __init__(self, action_slug):
        self.action_slug = action_slug
        super().__init__(f'Daily award cap reached for action "{action_slug}".')


@transaction.atomic
def award_points(user, action_slug, *, idempotency_key='', metadata=None, note='', awarded_by=None):
    """
    Server-side entry point for crediting points to a user. Intended callers:
    trusted in-process code (e.g. a future game's server-side result handler)
    or the staff-only manual-award view (awarded_by=staff request.user).

    Not exposed as a player-facing HTTP endpoint - see points/views.py.
    """
    action = PointAction.objects.get(slug=action_slug, is_active=True)

    if idempotency_key:
        existing = PointsLedgerEntry.objects.filter(
            user=user, action=action, idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing

    if action.max_awards_per_day is not None:
        today_count = PointsLedgerEntry.objects.filter(
            user=user,
            action=action,
            entry_type=PointsLedgerEntry.ENTRY_EARN,
            created_at__date=timezone.localdate(),
        ).count()
        if today_count >= action.max_awards_per_day:
            raise DailyCapExceeded(action.slug)

    balance, _ = PointsBalance.objects.select_for_update().get_or_create(user=user)
    balance.balance += action.points_value
    balance.lifetime_earned += action.points_value
    balance.save(update_fields=['balance', 'lifetime_earned', 'updated_at'])

    try:
        return PointsLedgerEntry.objects.create(
            user=user,
            entry_type=PointsLedgerEntry.ENTRY_EARN,
            delta=action.points_value,
            balance_after=balance.balance,
            action=action,
            idempotency_key=idempotency_key,
            metadata=metadata or {},
            note=note,
            awarded_by=awarded_by,
        )
    except IntegrityError:
        # Concurrent retry with the same idempotency_key lost the race; return the winner.
        transaction.set_rollback(True)
        return PointsLedgerEntry.objects.get(user=user, action=action, idempotency_key=idempotency_key)


@transaction.atomic
def apply_adjustment(user, staff_user, points_delta, note=''):
    """
    Manual staff correction (positive to award, negative to deduct), used by the
    Django admin "Award / Deduct Points" page. Routes through the ledger like every
    other points mutation so PointsBalance never gets hand-edited directly.
    """
    if points_delta == 0:
        raise ValueError('points_delta must be non-zero.')

    balance, _ = PointsBalance.objects.select_for_update().get_or_create(user=user)
    new_balance = balance.balance + points_delta
    if new_balance < 0:
        raise InsufficientPoints()

    balance.balance = new_balance
    if points_delta > 0:
        balance.lifetime_earned += points_delta
    balance.save(update_fields=['balance', 'lifetime_earned', 'updated_at'])

    entry = PointsLedgerEntry.objects.create(
        user=user,
        entry_type=PointsLedgerEntry.ENTRY_ADJUSTMENT,
        delta=points_delta,
        balance_after=balance.balance,
        note=note,
        awarded_by=staff_user,
    )
    return balance, entry


def _grant_round_xp(user, metadata, ledger_entry):
    """
    Best-effort "a round was played" XP signal, fired automatically from
    both settle_wager() and debit_balance() below - every wager-based game
    calls one of the two to charge the player (there is no other way to
    move money), so this is what makes a new game challenge-eligible with
    NO xp_hooks.py of its own: it only ever needs metadata={'game': '<slug>',
    ...} on its debit, which every caller already passes for its own
    record-keeping anyway.

    Fires the two shared, cross-game actions - qualified_gameplay (capped
    XP trickle) and gameplay_round (uncapped, 0 XP - what a "play N
    rounds, any game" challenge sources on) - plus, if they exist, this
    game's own <slug>_qualified_gameplay and <slug>_gameplay_round
    counterparts, which let a challenge be scoped to just this game
    instead of every game (see xp/admin.py's Challenge fieldset). Those
    two per-game actions are entirely optional: award_xp() raising
    XPAction.DoesNotExist because a game has no per-game counter seeded is
    swallowed exactly like a daily cap or a not-yet-eligible challenge
    would be - so a brand-new game gets the two shared actions for free
    the moment it exists, and can be scoped to specifically later purely
    by creating one XPAction row (slug=f'{game}_gameplay_round') in
    admin. No code, no migration, no deploy.

    Lazy-imports xp.services/xp.models to avoid a hard points -> xp
    dependency at module load time (points is a lower-level app several
    others import - mirrors the lazy cross-app imports already used
    elsewhere, e.g. games/views.py's cross-game stat queries). Entirely
    best-effort: nothing here may ever propagate and roll back the wallet
    movement it's called after.
    """
    game_slug = (metadata or {}).get('game')
    if not game_slug:
        return  # not a game-attributed debit (e.g. a manual admin adjustment) - nothing to award

    from xp.models import XPAction
    from xp.services import ChallengeNotYetEligible
    from xp.services import DailyCapExceeded as XPDailyCapExceeded
    from xp.services import award_matching_challenges, award_xp

    for slug in (
        'qualified_gameplay',
        f'{game_slug}_qualified_gameplay',
        'gameplay_round',
        f'{game_slug}_gameplay_round',
    ):
        try:
            award_xp(user, slug, idempotency_key=f'{slug}:{ledger_entry.id}', note=f'{slug} ({game_slug})')
        except (XPAction.DoesNotExist, XPDailyCapExceeded, ChallengeNotYetEligible):
            pass

    # award_matching_challenges is itself fully best-effort per challenge
    # and simply finds nothing when a source slug has no XPAction - no
    # try/except needed here, matching how every game hook already calls it.
    award_matching_challenges(user, source_action_slug='gameplay_round', note=f'Challenge: play rounds ({game_slug})')
    award_matching_challenges(user, source_action_slug=f'{game_slug}_gameplay_round', note=f'Challenge: play {game_slug} rounds')


@transaction.atomic
def settle_wager(user, *, wager_amount, payout_amount, entry_type=PointsLedgerEntry.ENTRY_GAME_ROUND,
                  metadata=None, note=''):
    """
    Atomically debits `wager_amount` and credits `payout_amount` for an instantly-resolved
    wager-style game round (no pending/approval step, unlike redemptions). Records a single
    net-delta ledger entry. Raises InsufficientPoints if the user can't cover the wager.
    """
    if wager_amount <= 0:
        raise ValueError('wager_amount must be positive.')
    if payout_amount < 0:
        raise ValueError('payout_amount cannot be negative.')

    balance, _ = PointsBalance.objects.select_for_update().get_or_create(user=user)
    if balance.balance < wager_amount:
        raise InsufficientPoints()

    net_delta = payout_amount - wager_amount
    balance.balance += net_delta
    balance.save(update_fields=['balance', 'updated_at'])

    entry = PointsLedgerEntry.objects.create(
        user=user,
        entry_type=entry_type,
        delta=net_delta,
        balance_after=balance.balance,
        metadata=metadata or {},
        note=note,
    )
    _grant_round_xp(user, metadata, entry)
    return balance, entry


@transaction.atomic
def debit_balance(user, *, amount, entry_type=PointsLedgerEntry.ENTRY_GAME_ROUND, metadata=None, note=''):
    """
    Atomically debits `amount` with no corresponding credit in the same
    call - for games whose outcome isn't known yet at wager time (e.g. a
    crash game's play is charged immediately, with any payout settled
    later via credit_balance() once the round resolves). Plinko/Slots
    settle both legs in one instant call via settle_wager(); this is the
    split-in-time equivalent of just its debit half. Raises
    InsufficientPoints if the user can't cover it - callers must not
    create a round/ledger row when this raises.
    """
    if amount <= 0:
        raise ValueError('amount must be positive.')

    balance, _ = PointsBalance.objects.select_for_update().get_or_create(user=user)
    if balance.balance < amount:
        raise InsufficientPoints()

    balance.balance -= amount
    balance.save(update_fields=['balance', 'updated_at'])

    entry = PointsLedgerEntry.objects.create(
        user=user,
        entry_type=entry_type,
        delta=-amount,
        balance_after=balance.balance,
        metadata=metadata or {},
        note=note,
    )
    _grant_round_xp(user, metadata, entry)
    return balance, entry


@transaction.atomic
def credit_balance(user, *, amount, entry_type=PointsLedgerEntry.ENTRY_GAME_ROUND, metadata=None, note=''):
    """The credit-later half of the debit_balance() split - see its docstring."""
    if amount <= 0:
        raise ValueError('amount must be positive.')

    balance, _ = PointsBalance.objects.select_for_update().get_or_create(user=user)
    balance.balance += amount
    balance.save(update_fields=['balance', 'updated_at'])

    entry = PointsLedgerEntry.objects.create(
        user=user,
        entry_type=entry_type,
        delta=amount,
        balance_after=balance.balance,
        metadata=metadata or {},
        note=note,
    )
    return balance, entry


@transaction.atomic
def create_redemption_request(user, points_amount, note='', reward_description=''):
    config = PointsRedemptionConfig.get_solo()
    if points_amount < config.min_redemption_points:
        raise BelowMinimumRedemption(config.min_redemption_points)

    balance, _ = PointsBalance.objects.select_for_update().get_or_create(user=user)
    if balance.balance < points_amount:
        raise InsufficientPoints()

    active = (
        PointsRedemptionRequest.objects
        .select_for_update()
        .filter(user=user, status__in=PointsRedemptionRequest.ACTIVE_STATUSES)
        .first()
    )
    if active:
        raise ActiveRedemptionExists()

    balance.balance -= points_amount
    balance.save(update_fields=['balance', 'updated_at'])

    redemption_request = PointsRedemptionRequest.objects.create(
        user=user,
        points_amount=points_amount,
        note=note,
        reward_description=reward_description,
        conversion_rate_snapshot=config.rp_to_credit_rate,
        hi_rollin_credit_amount=(Decimal(points_amount) * config.rp_to_credit_rate).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        ),
    )
    PointsLedgerEntry.objects.create(
        user=user,
        entry_type=PointsLedgerEntry.ENTRY_REDEMPTION_HOLD,
        delta=-points_amount,
        balance_after=balance.balance,
        redemption_request=redemption_request,
    )
    return redemption_request


@transaction.atomic
def review_redemption_request(request_obj, staff_user, new_status, staff_note=''):
    request_obj = (
        PointsRedemptionRequest.objects
        .select_for_update()
        .select_related('user')
        .get(pk=request_obj.pk)
    )

    if request_obj.status == PointsRedemptionRequest.STATUS_COMPLETED:
        raise ValueError('This request is already completed.')
    if request_obj.status == PointsRedemptionRequest.STATUS_REJECTED:
        raise ValueError('This request is already rejected.')
    if request_obj.status == PointsRedemptionRequest.STATUS_PENDING and new_status == PointsRedemptionRequest.STATUS_COMPLETED:
        raise ValueError('Approve this request before completing it.')
    if request_obj.status == PointsRedemptionRequest.STATUS_APPROVED and new_status != PointsRedemptionRequest.STATUS_COMPLETED:
        raise ValueError('Approved requests can only be completed.')
    if new_status == PointsRedemptionRequest.STATUS_COMPLETED and request_obj.status != PointsRedemptionRequest.STATUS_APPROVED:
        raise ValueError('This request cannot be completed.')

    if new_status == PointsRedemptionRequest.STATUS_REJECTED:
        balance, _ = PointsBalance.objects.select_for_update().get_or_create(user=request_obj.user)
        balance.balance += request_obj.points_amount
        balance.save(update_fields=['balance', 'updated_at'])
        PointsLedgerEntry.objects.create(
            user=request_obj.user,
            entry_type=PointsLedgerEntry.ENTRY_REDEMPTION_REFUND,
            delta=request_obj.points_amount,
            balance_after=balance.balance,
            redemption_request=request_obj,
        )
    elif new_status == PointsRedemptionRequest.STATUS_COMPLETED:
        balance, _ = PointsBalance.objects.select_for_update().get_or_create(user=request_obj.user)
        PointsLedgerEntry.objects.create(
            user=request_obj.user,
            entry_type=PointsLedgerEntry.ENTRY_REDEMPTION_FINALIZE,
            delta=0,
            balance_after=balance.balance,
            redemption_request=request_obj,
        )

    request_obj.mark_reviewed(staff_user, new_status, staff_note)
    request_obj.save(update_fields=['status', 'staff_note', 'reviewed_by', 'reviewed_at', 'completed_at', 'updated_at'])
    return request_obj
