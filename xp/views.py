from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .models import XPAction, XPBalance, XPLedgerEntry
from .serializers import XPActionSerializer, XPStatusSerializer

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
    return Response(XPStatusSerializer(balance).data)


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


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def action_list_view(request):
    if not _is_staff_user(request.user):
        return Response({'error': 'Only staff can view XP actions.'}, status=status.HTTP_403_FORBIDDEN)

    actions = XPAction.objects.all()
    return Response(XPActionSerializer(actions, many=True).data)
