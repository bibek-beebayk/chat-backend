from datetime import timedelta

from django.db.models import F, Max
from django.utils import timezone
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .models import Game
from .serializers import GameSerializer


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def game_list_view(request):
    games = Game.objects.filter(is_active=True)
    # Pass request context so ImageField.to_representation resolves
    # `thumbnail` to an absolute URL - required in local dev, where
    # FileSystemStorage returns a bare relative /media/... path (S3Storage
    # in staging/prod already returns an absolute URL either way).
    return Response(GameSerializer(games, many=True, context={'request': request}).data)


RANGE_DELTAS = {
    'week': timedelta(days=7),
    'month': timedelta(days=30),
}


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def player_stats_view(request):
    """
    Cross-game play stats for the profile page - aggregated live across the
    three round tables (no aggregate counters cached anywhere), each game's
    own real win-signal field. Lazy-imported for the same reason as
    xp.views._has_first_win: avoids a circular import with the low-level
    xp app these game apps already depend on.
    """
    from plinko.models import PlinkoRound
    from rocket.models import RocketRound
    from slots.models import SlotRound

    range_param = request.query_params.get('range', 'all')
    if range_param not in RANGE_DELTAS:
        range_param = 'all'
    delta = RANGE_DELTAS.get(range_param)
    since = timezone.now() - delta if delta else None

    user = request.user
    plinko_qs = PlinkoRound.objects.filter(user=user)
    slots_qs = SlotRound.objects.filter(user=user)
    rocket_qs = RocketRound.objects.filter(user=user)
    if since:
        plinko_qs = plinko_qs.filter(created_at__gte=since)
        slots_qs = slots_qs.filter(created_at__gte=since)
        rocket_qs = rocket_qs.filter(created_at__gte=since)

    rounds_played = plinko_qs.count() + slots_qs.count() + rocket_qs.count()

    total_wins = (
        plinko_qs.filter(payout_amount__gt=F('wager_amount')).count()
        + slots_qs.filter(payout_amount__gt=0).count()
        + rocket_qs.filter(status=RocketRound.STATUS_CASHED_OUT).count()
    )

    multipliers = []
    plinko_max = plinko_qs.aggregate(m=Max('multiplier'))['m']
    if plinko_max is not None:
        multipliers.append(plinko_max)
    slots_max = slots_qs.aggregate(m=Max('total_multiplier'))['m']
    if slots_max is not None:
        multipliers.append(slots_max)
    rocket_max = rocket_qs.filter(status=RocketRound.STATUS_CASHED_OUT).aggregate(m=Max('cashout_multiplier'))['m']
    if rocket_max is not None:
        multipliers.append(rocket_max)
    highest_multiplier = max(multipliers) if multipliers else None

    return Response({
        'range': range_param,
        'rounds_played': rounds_played,
        'total_wins': total_wins,
        'highest_multiplier': str(highest_multiplier) if highest_multiplier is not None else None,
    })


RECENT_WINS_LIMIT = 8


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def recent_wins_view(request, slug):
    """
    Most recent winning rounds for one game, across all real (non-test)
    players - powers the game details page's "Recent Wins" list. Each
    game's round table has its own win-signal and multiplier field, same
    as player_stats_view above; lazy-imported for the same circular-import
    reason. is_test_user=False keeps seeded/QA accounts out of a feed real
    players see.
    """
    from plinko.models import PlinkoRound
    from rocket.models import RocketRound
    from slots.models import SlotRound

    if slug == 'plinko':
        qs = (
            PlinkoRound.objects
            .filter(payout_amount__gt=F('wager_amount'), user__is_test_user=False)
            .select_related('user')
            .order_by('-created_at')[:RECENT_WINS_LIMIT]
        )
        entries = [(r.user, r.multiplier, r.created_at) for r in qs]
    elif slug == 'slots':
        qs = (
            SlotRound.objects
            .filter(payout_amount__gt=0, user__is_test_user=False)
            .select_related('user')
            .order_by('-created_at')[:RECENT_WINS_LIMIT]
        )
        entries = [(r.user, r.total_multiplier, r.created_at) for r in qs]
    elif slug == 'rocket':
        qs = (
            RocketRound.objects
            .filter(status=RocketRound.STATUS_CASHED_OUT, user__is_test_user=False)
            .select_related('user')
            .order_by('-created_at')[:RECENT_WINS_LIMIT]
        )
        entries = [(r.user, r.cashout_multiplier, r.created_at) for r in qs]
    else:
        return Response({'error': 'Unknown game.'}, status=404)

    return Response([
        {
            'username': user.username,
            'multiplier': str(multiplier),
            'created_at': created_at,
        }
        for user, multiplier, created_at in entries
    ])
