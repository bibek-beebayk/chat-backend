from django.db.models import F
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from chat_project.url_utils import build_public_absolute_uri
from .models import Tier, XPAction, XPBalance, XPLedgerEntry
from .ranks import rank_for_xp, sub_ranges_for_tier
from .serializers import XPActionSerializer, XPStatusSerializer

# Achievements shown on the player profile - each backed by a real, already-
# earnable signal rather than a fabricated badge. Three are existing XPAction
# slugs (already seeded and functional, just never surfaced in any UI before
# now); "first_win" isn't an XP action at all, it's a direct cross-game query
# (see _has_first_win below).
ACHIEVEMENT_DEFINITIONS = [
    {'slug': 'streak_7day', 'label': '7-Day Streak'},
    {'slug': 'first_win', 'label': 'First Win'},
    {'slug': 'rocket_cashout_above_10x', 'label': 'Moon Walker'},
    {'slug': 'rocket_five_alive', 'label': 'Five Alive'},
]

# The two real player-facing "daily checklist" actions - NOT qualified_gameplay,
# which is background per-round trickle with no natural target the player
# checks off. Keeping this list here (not a model flag) since "which actions
# are checklist-worthy" is a display concern, not an award-eligibility one.
DAILY_CHECKLIST_SLUGS = ['daily_login', 'daily_challenge_rounds']


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
    Today's progress toward the player-facing daily checklist actions, using
    the EXACT same "today" boundary (timezone.localdate() on created_at__date)
    that xp.services.award_xp()'s own daily-cap/challenge eligibility checks
    use - so this can never disagree with the real award state.
    """
    today = timezone.localdate()
    actions = {a.slug: a for a in XPAction.objects.filter(slug__in=DAILY_CHECKLIST_SLUGS, is_active=True)}

    results = []
    for slug in DAILY_CHECKLIST_SLUGS:
        action = actions.get(slug)
        if not action:
            continue

        # For a plain daily action (daily_login), progress is against its own
        # award count today. For a challenge action (daily_challenge_rounds),
        # progress is against its challenge_source_action's award count today
        # - the same count xp.services.award_xp() checks for eligibility.
        target = action.challenge_target_count or 1
        count_action_id = action.challenge_source_action_id or action.id
        current_count = XPLedgerEntry.objects.filter(
            user=request.user,
            action_id=count_action_id,
            entry_type=XPLedgerEntry.ENTRY_EARN,
            created_at__date=today,
        ).count()
        completed = XPLedgerEntry.objects.filter(
            user=request.user,
            action=action,
            entry_type=XPLedgerEntry.ENTRY_EARN,
            created_at__date=today,
        ).exists()

        results.append({
            'slug': action.slug,
            'label': action.label,
            'xp_value': action.xp_value,
            'target_count': target,
            'current_count': min(current_count, target),
            'completed': completed,
        })

    return Response(results)


def _has_first_win(user):
    # Lazy imports - xp is a low-level app other games import from (via
    # award_xp), so importing their models back at module level here risks
    # a circular import. A local import avoids that entirely.
    from plinko.models import PlinkoRound
    from rocket.models import RocketRound
    from slots.models import SlotRound

    if PlinkoRound.objects.filter(user=user, payout_amount__gt=F('wager_amount')).exists():
        return True
    if SlotRound.objects.filter(user=user, payout_amount__gt=0).exists():
        return True
    if RocketRound.objects.filter(user=user, status=RocketRound.STATUS_CASHED_OUT).exists():
        return True
    return False


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def achievements_view(request):
    user = request.user
    earned_slugs = {
        entry.action.slug: entry.created_at
        for entry in XPLedgerEntry.objects.filter(
            user=user,
            entry_type=XPLedgerEntry.ENTRY_EARN,
            action__slug__in=[d['slug'] for d in ACHIEVEMENT_DEFINITIONS if d['slug'] != 'first_win'],
        ).select_related('action').order_by('created_at')
    }
    has_first_win = _has_first_win(user)

    results = []
    for definition in ACHIEVEMENT_DEFINITIONS:
        slug = definition['slug']
        if slug == 'first_win':
            unlocked = has_first_win
            earned_at = None
        else:
            unlocked = slug in earned_slugs
            earned_at = earned_slugs.get(slug)
        results.append({
            'slug': slug,
            'label': definition['label'],
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
