from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from points.services import InsufficientPoints
from .constants import (
    ACCEL_EXPONENT,
    AUTO_CASHOUT_QUICK_OPTIONS,
    COUNTDOWN_SECONDS,
    GAME_VERSION,
    GROWTH_RATE,
    HISTORY_LIMIT,
    MAX_AUTO_CASHOUT_MULTIPLIER,
    MAX_WAGER,
    MIN_AUTO_CASHOUT_MULTIPLIER,
    MIN_WAGER,
    WAGER_QUICK_AMOUNTS,
)
from .models import RocketRound
from .serializers import RocketHistoryItemSerializer, RocketPlayRequestSerializer, RocketRoundSerializer
from .services import (
    ActiveRoundExists,
    NoActiveRound,
    RocketGameUnavailable,
    RoundAlreadyResolved,
    TooEarlyToCashOut,
    cash_out,
    get_current_round,
    place_bet,
)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def config_view(request):
    return Response({
        'enabled': True,
        'game_version': GAME_VERSION,
        'min_wager': str(MIN_WAGER),
        'max_wager': str(MAX_WAGER),
        'wager_quick_amounts': WAGER_QUICK_AMOUNTS,
        'min_auto_cashout_multiplier': str(MIN_AUTO_CASHOUT_MULTIPLIER),
        'max_auto_cashout_multiplier': str(MAX_AUTO_CASHOUT_MULTIPLIER),
        'auto_cashout_quick_options': [str(v) for v in AUTO_CASHOUT_QUICK_OPTIONS],
        'countdown_seconds': str(COUNTDOWN_SECONDS),
        # The multiplier curve is not secret (only crash_point is) -
        # exposed so the frontend can interpolate a smooth animation
        # between polls using the exact same formula as
        # rocket/services.py::multiplier_at_elapsed, instead of only
        # updating visually once per ~150ms poll.
        'growth_rate': str(GROWTH_RATE),
        'accel_exponent': str(ACCEL_EXPONENT),
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def play_view(request):
    if getattr(request.user, 'user_type', None) != 'player':
        return Response({'error': 'Only players can play Rollin Rocket.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = RocketPlayRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        round_obj, created = place_bet(
            request.user,
            wager_amount=data['wager_amount'],
            auto_cashout_multiplier=data.get('auto_cashout_multiplier'),
            client_request_id=data.get('client_request_id', ''),
        )
    except RocketGameUnavailable:
        return Response({'error': 'Rollin Rocket is currently unavailable.'}, status=status.HTTP_400_BAD_REQUEST)
    except InsufficientPoints:
        return Response({'error': 'You do not have enough Reward Points for this play.'}, status=status.HTTP_400_BAD_REQUEST)
    except ActiveRoundExists as exc:
        return Response(
            {
                'error': 'You already have an active Rollin Rocket round in progress.',
                'active_round': RocketRoundSerializer(exc.round_obj).data,
            },
            status=status.HTTP_409_CONFLICT,
        )

    return Response(RocketRoundSerializer(round_obj).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def current_round_view(request):
    """
    Polled by the frontend every ~150ms while a round is active, and once on
    mount to restore an in-flight round after a refresh/reconnect. Returns
    null when there's nothing active (fresh betting screen).
    """
    round_obj = get_current_round(request.user)
    if not round_obj:
        return Response(None)
    return Response(RocketRoundSerializer(round_obj).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def cashout_view(request):
    try:
        round_obj = cash_out(request.user)
    except NoActiveRound:
        return Response({'error': 'No active Rollin Rocket round to cash out.'}, status=status.HTTP_400_BAD_REQUEST)
    except TooEarlyToCashOut:
        return Response({'error': 'The rocket has not launched yet.'}, status=status.HTTP_400_BAD_REQUEST)
    except RoundAlreadyResolved as exc:
        # Not an error from the player's point of view - either a
        # duplicate Cash Out click (already cashed out) or the rocket
        # crashed in the same instant they tried. Return the authoritative
        # final state either way, same idempotent shape as a fresh cashout.
        return Response(RocketRoundSerializer(exc.round_obj).data, status=status.HTTP_200_OK)

    return Response(RocketRoundSerializer(round_obj).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def history_view(request):
    rounds = RocketRound.objects.filter(
        user=request.user,
        status__in=[RocketRound.STATUS_CASHED_OUT, RocketRound.STATUS_CRASHED],
    )[:HISTORY_LIMIT]
    return Response(RocketHistoryItemSerializer(rounds, many=True).data)
