from django.db import IntegrityError, transaction
from django.utils import timezone
from notifications.services import create_notification
from .models import XPAction, XPBalance, XPLedgerEntry
from .ranks import rank_by_slug, rank_for_xp


def rank_up_bonus_rp(slug):
    """One-time RP credit for first reaching the given tier (0 if none / unknown)."""
    tier = rank_by_slug(slug)
    return tier.rank_up_bonus_rp if tier else 0


def _apply_rank_up_bonus(user, new_tier, balance):
    # Flags a fresh rank-up for the frontend's "Level Up!" celebration
    # (see xp.serializers.XPStatusSerializer.get_pending_level_up and
    # xp.views.acknowledge_level_up_view) - cleared once shown/acknowledged.
    balance.pending_celebration_rank = new_tier.slug
    balance.save(update_fields=['pending_celebration_rank'])

    bonus = new_tier.rank_up_bonus_rp
    if not bonus:
        return
    # Lazy import: points/ has no reverse dependency on xp/, but every other
    # cross-app call in this module stays lazy/local for consistency.
    from points.models import PointsLedgerEntry
    from points.services import credit_balance

    credit_balance(
        user,
        amount=bonus,
        entry_type=PointsLedgerEntry.ENTRY_EARN,
        metadata={'reason': 'rank_up_bonus', 'rank': new_tier.slug},
        note=f'Rank-up bonus for reaching {new_tier.label}',
    )


class DailyCapExceeded(Exception):
    def __init__(self, action_slug):
        self.action_slug = action_slug
        super().__init__(f'Daily XP award cap reached for action "{action_slug}".')


class ChallengeNotYetEligible(Exception):
    def __init__(self, action_slug, current_count, target_count):
        self.action_slug = action_slug
        self.current_count = current_count
        self.target_count = target_count
        super().__init__(
            f'Challenge "{action_slug}" not yet eligible: {current_count}/{target_count} today.'
        )


@transaction.atomic
def award_xp(user, action_slug, *, idempotency_key='', metadata=None, note='', awarded_by=None):
    """
    Server-side entry point for crediting XP to a user. Mirrors
    points.services.award_points() exactly (idempotency-key dedup, daily
    cap, select_for_update balance lock, IntegrityError race recovery),
    plus: an optional "daily challenge" eligibility gate, and rank-up
    detection that fires an in-app notification.

    Not exposed as a player-facing HTTP endpoint - see xp/views.py.
    """
    action = XPAction.objects.get(slug=action_slug, is_active=True)

    if idempotency_key:
        existing = XPLedgerEntry.objects.filter(
            user=user, action=action, idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing

    if action.max_awards_per_day is not None:
        today_count = XPLedgerEntry.objects.filter(
            user=user,
            action=action,
            entry_type=XPLedgerEntry.ENTRY_EARN,
            created_at__date=timezone.localdate(),
        ).count()
        if today_count >= action.max_awards_per_day:
            raise DailyCapExceeded(action.slug)

    if action.challenge_target_count is not None:
        now = timezone.now()
        if not action.is_challenge_open(now=now):
            # Outside the challenge's window entirely - not started yet, or
            # (an event) already closed. Reused ChallengeNotYetEligible for
            # both cases rather than a new exception, so every existing
            # best-effort call site (every game's xp_hooks.py) keeps
            # working unchanged - they already catch this one.
            raise ChallengeNotYetEligible(action.slug, 0, action.challenge_target_count)

        window_start, window_end = action.challenge_window(now=now)
        source_qs = XPLedgerEntry.objects.filter(
            user=user,
            action_id__in=action.challenge_source_actions.values_list('id', flat=True),
            entry_type=XPLedgerEntry.ENTRY_EARN,
            created_at__gte=window_start,
        )
        if window_end is not None:
            source_qs = source_qs.filter(created_at__lte=window_end)
        window_source_count = source_qs.count()
        if window_source_count < action.challenge_target_count:
            raise ChallengeNotYetEligible(action.slug, window_source_count, action.challenge_target_count)

    balance, _ = XPBalance.objects.select_for_update().get_or_create(user=user)
    old_rank_slug = balance.rank_slug or rank_for_xp(0).slug
    balance.total_xp += action.xp_value
    new_tier = rank_for_xp(balance.total_xp)
    balance.rank_slug = new_tier.slug
    balance.rank_updated_at = timezone.now()
    balance.save(update_fields=['total_xp', 'rank_slug', 'rank_updated_at', 'updated_at'])

    try:
        entry = XPLedgerEntry.objects.create(
            user=user,
            entry_type=XPLedgerEntry.ENTRY_EARN,
            delta=action.xp_value,
            xp_after=balance.total_xp,
            rank_after=new_tier.slug,
            action=action,
            idempotency_key=idempotency_key,
            metadata=metadata or {},
            note=note,
            awarded_by=awarded_by,
        )
    except IntegrityError:
        # Concurrent retry with the same idempotency_key lost the race; return the winner.
        transaction.set_rollback(True)
        return XPLedgerEntry.objects.get(user=user, action=action, idempotency_key=idempotency_key)

    if new_tier.slug != old_rank_slug:
        create_notification(
            user,
            title=f'Rank up! You reached {new_tier.label}',
            body=f'You earned {action.xp_value} XP and ranked up to {new_tier.label}.',
        )
        _apply_rank_up_bonus(user, new_tier, balance)

    return entry


def award_matching_challenges(user, *, source_action_slug, note=''):
    """
    Attempts every currently configured challenge that counts
    `source_action_slug` (e.g. 'gameplay_round', or a per-game counter like
    'plinko_gameplay_round') among its source actions - called once by a
    game right after it fires that counter action.

    This is what makes a brand-new daily, weekly, or event challenge -
    scoped to one game, several games, or every game - buildable purely
    from Django admin. Before this, each game hardcoded the one challenge
    slug ('daily_challenge_rounds') it attempted to award, so a second
    "play N rounds"-shaped challenge needed a matching code change in
    every game's xp_hooks.py. This discovers every XPAction configured
    against that source instead, so nothing here needs to change when
    staff adds one, however it's scoped - the game-scoping (which of the
    per-game counters a challenge lists in challenge_source_actions) and
    the period (daily/weekly/event) both live on XPAction itself, not here.

    Each challenge is attempted independently and best-effort - one being
    not-yet-eligible, capped, or misconfigured must never block another,
    and none of this may ever propagate to the caller, which is always a
    wallet-settlement hook.
    """
    challenges = XPAction.objects.filter(
        is_active=True,
        challenge_source_actions__slug=source_action_slug,
        challenge_target_count__isnull=False,
    ).distinct()
    for action in challenges:
        # The period key changes when a recurring window rolls over (a new
        # day, a new week), so the same weekly challenge is earnable again
        # next week under a fresh idempotency key - and an event, which has
        # exactly one instance ever, keys off its own id instead.
        idempotency_key = f'{action.slug}:{user.id}:{action.challenge_period_key()}'
        try:
            award_xp(
                user, action.slug,
                idempotency_key=idempotency_key,
                note=note or f'Challenge: {action.label}',
            )
        except (XPAction.DoesNotExist, DailyCapExceeded, ChallengeNotYetEligible):
            pass


@transaction.atomic
def apply_adjustment(user, staff_user, xp_delta, note=''):
    """
    Manual staff correction (positive to award, negative to deduct) -
    mirrors points.services.apply_adjustment(). XP may legitimately be
    corrected downward (e.g. reversing an abusive award), but total_xp
    itself must never go negative.
    """
    if xp_delta == 0:
        raise ValueError('xp_delta must be non-zero.')

    balance, _ = XPBalance.objects.select_for_update().get_or_create(user=user)
    new_total = balance.total_xp + xp_delta
    if new_total < 0:
        raise ValueError('Adjustment would make total_xp negative.')

    old_rank_slug = balance.rank_slug or rank_for_xp(0).slug
    balance.total_xp = new_total
    new_tier = rank_for_xp(balance.total_xp)
    balance.rank_slug = new_tier.slug
    balance.rank_updated_at = timezone.now()
    balance.save(update_fields=['total_xp', 'rank_slug', 'rank_updated_at', 'updated_at'])

    entry = XPLedgerEntry.objects.create(
        user=user,
        entry_type=XPLedgerEntry.ENTRY_ADJUSTMENT,
        delta=xp_delta,
        xp_after=balance.total_xp,
        rank_after=new_tier.slug,
        note=note,
        awarded_by=staff_user,
    )

    if new_tier.slug != old_rank_slug:
        create_notification(
            user,
            title=f'Rank up! You reached {new_tier.label}',
            body=f'You ranked up to {new_tier.label}.',
        )
        _apply_rank_up_bonus(user, new_tier, balance)

    return balance, entry
