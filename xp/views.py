from django.db.models import F
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from chat_project.url_utils import build_public_absolute_uri
from .models import Tier, XPAction, XPBalance, XPLedgerEntry
from .ranks import rank_for_xp, sub_ranges_for_tier
from .serializers import XPActionSerializer, XPStatusSerializer

# Which actions are player-facing challenges/achievements, in what order,
# with what label, icon and link, is all data on XPAction now
# (is_daily_checklist / is_achievement / display_order / icon / action_url)
# rather than lists here. That means adding a challenge is creating a row in
# Django admin - no code change, no deploy, and no matching change in the
# frontend, which reads every one of those fields off the API response.
#
# "first_win" is the one achievement not awarded as XP: it has an XPAction
# row so the list stays a single ordered query, but whether it is unlocked
# comes from a live cross-game query (see _has_first_win below).
FIRST_WIN_SLUG = 'first_win'


def _is_staff_user(user):
    return bool(user and user.is_authenticated and getattr(user, 'user_type', None) == 'staff')


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def status_view(request):
    balance, _ = XPBalance.objects.get_or_create(user=request.user)
    return Response(XPStatusSerializer(balance, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def acknowledge_level_up_view(request):
    """Clears the pending "Level Up!" celebration flag once the frontend has shown it - see XPBalance.pending_celebration_rank."""
    balance, _ = XPBalance.objects.get_or_create(user=request.user)
    if balance.pending_celebration_rank:
        balance.pending_celebration_rank = ''
        balance.save(update_fields=['pending_celebration_rank'])
    return Response(XPStatusSerializer(balance, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def daily_progress_view(request):
    """
    Current progress toward every player-facing checklist action - despite
    the name/URL (kept for backward compatibility), this is not daily-only:
    an action's own challenge_period (daily/weekly/event, see XPAction)
    decides which window its progress is measured against, via
    XPAction.challenge_window() - the EXACT same method
    xp.services.award_xp()'s own eligibility check calls, so this can never
    disagree with the real award state. An event action is only listed
    while its window is actually open (is_challenge_open()) - before it
    starts there's nothing to show yet, and once it ends it drops off the
    checklist rather than lingering as a stale tile (see is_achievement on
    XPAction for challenges that should be remembered permanently instead).
    """
    now = timezone.now()
    actions = (
        XPAction.objects
        .filter(is_daily_checklist=True, is_active=True)
        .order_by('display_order', 'slug')
    )

    results = []
    for action in actions:
        is_challenge = action.challenge_target_count is not None
        if is_challenge and not action.is_challenge_open(now=now):
            continue

        window_start, window_end = action.challenge_window(now=now)

        # For a plain action with no target (daily_login), progress is
        # against its own award count in its window. For a challenge
        # action, progress is against the combined award count of every
        # action in challenge_source_actions in that same window - the
        # same count xp.services.award_xp() checks for eligibility. This is
        # what a multi-game challenge sums across: e.g. Plinko + Rocket
        # rounds both count if both of their counters are listed.
        target = action.challenge_target_count or 1
        source_ids = list(action.challenge_source_actions.values_list('id', flat=True)) or [action.id]
        count_qs = XPLedgerEntry.objects.filter(
            user=request.user,
            action_id__in=source_ids,
            entry_type=XPLedgerEntry.ENTRY_EARN,
            created_at__gte=window_start,
        )
        completed_qs = XPLedgerEntry.objects.filter(
            user=request.user,
            action=action,
            entry_type=XPLedgerEntry.ENTRY_EARN,
            created_at__gte=window_start,
        )
        if window_end is not None:
            count_qs = count_qs.filter(created_at__lte=window_end)
            completed_qs = completed_qs.filter(created_at__lte=window_end)
        current_count = count_qs.count()
        completed = completed_qs.exists()

        results.append({
            'slug': action.slug,
            # display_label resolves any {target} placeholder, so the count
            # in the label always matches challenge_target_count.
            'label': action.display_label,
            'description': action.description,
            'icon': action.icon,
            # Blank means "not directly actionable" - the client renders the
            # tile without a link rather than guessing a destination.
            'action_url': action.action_url,
            'xp_value': action.xp_value,
            'target_count': target,
            'current_count': min(current_count, target),
            'completed': completed,
            'challenge_period': action.challenge_period,
            # When this window's progress next resets (daily/weekly) or
            # closes for good (event) - display-only, lets the frontend
            # show a correct countdown/label for any period without
            # hardcoding per-slug knowledge of which challenges are weekly
            # or time-limited.
            'resets_at': action.challenge_resets_at(now=now),
        })

    return Response(results)


def _has_first_win(user):
    # Lazy imports - xp is a low-level app other games import from (via
    # award_xp), so importing their models back at module level here risks
    # a circular import. A local import avoids that entirely.
    from hilo.models import HiLoRound
    from plinko.models import PlinkoRound
    from rocket.models import RocketRound
    from slots.models import SlotRound

    if PlinkoRound.objects.filter(user=user, payout_amount__gt=F('wager_amount')).exists():
        return True
    if SlotRound.objects.filter(user=user, payout_amount__gt=0).exists():
        return True
    if RocketRound.objects.filter(user=user, status=RocketRound.STATUS_CASHED_OUT).exists():
        return True
    if HiLoRound.objects.filter(user=user, status=HiLoRound.STATUS_CASHED_OUT).exists():
        return True
    return False


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def achievements_view(request):
    user = request.user
    actions = list(
        XPAction.objects
        .filter(is_achievement=True, is_active=True)
        .order_by('display_order', 'slug')
    )

    earned_slugs = {
        entry.action.slug: entry.created_at
        for entry in XPLedgerEntry.objects.filter(
            user=user,
            entry_type=XPLedgerEntry.ENTRY_EARN,
            action__slug__in=[a.slug for a in actions if a.slug != FIRST_WIN_SLUG],
        ).select_related('action').order_by('created_at')
    }
    # Only pay for the cross-game query if that achievement is actually
    # enabled - staff can switch it off like any other row.
    has_first_win = _has_first_win(user) if any(a.slug == FIRST_WIN_SLUG for a in actions) else False

    results = []
    for action in actions:
        if action.slug == FIRST_WIN_SLUG:
            unlocked = has_first_win
            earned_at = None
        else:
            unlocked = action.slug in earned_slugs
            earned_at = earned_slugs.get(action.slug)
        results.append({
            'slug': action.slug,
            'label': action.display_label,
            'description': action.description,
            'icon': action.icon,
            'unlocked': unlocked,
            'earned_at': earned_at,
        })

    return Response(results)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def rank_tiers_view(request):
    """
    Every active rank tier (xp.Tier - admin-managed: label, XP threshold,
    sub-ranges, rank-up bonus, tagline, badge art) merged with the caller's
    live position. Powers both the Rollin Levels overview list and every
    per-tier detail page from a single fetch - the data is small and
    identical for every caller aside from which tier is "current"/"unlocked".
    """
    balance, _ = XPBalance.objects.get_or_create(user=request.user)
    current_tier = rank_for_xp(balance.total_xp)
    tier_rows = list(Tier.objects.filter(is_active=True).order_by('min_xp'))

    tiers = []
    for i, tier in enumerate(tier_rows):
        next_min_xp = tier_rows[i + 1].min_xp if i + 1 < len(tier_rows) else None
        tiers.append({
            'slug': tier.slug,
            'label': tier.name,
            'min_xp': tier.min_xp,
            'max_xp': (next_min_xp - 1) if next_min_xp is not None else None,
            'sub_ranges': sub_ranges_for_tier(tier.slug),
            'rank_up_bonus_rp': tier.rank_up_bonus_rp or None,
            'tagline': tier.tagline,
            'badge_url': build_public_absolute_uri(request, tier.badge.url) if tier.badge else None,
            'is_current': tier.slug == current_tier.slug,
            'is_unlocked': balance.total_xp >= tier.min_xp,
        })

    return Response({
        'caller': {
            'total_xp': balance.total_xp,
            'rank': current_tier.slug,
        },
        'tiers': tiers,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def action_list_view(request):
    if not _is_staff_user(request.user):
        return Response({'error': 'Only staff can view XP actions.'}, status=status.HTTP_403_FORBIDDEN)

    actions = XPAction.objects.all()
    return Response(XPActionSerializer(actions, many=True).data)
