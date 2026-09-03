from decimal import Decimal

from django.db.models import Count, Max, Q, Sum
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from points.services import InsufficientPoints
from .constants import (
    GAME_VERSION,
    HISTORY_LIMIT,
    HOUSE_EDGE,
    MAX_MULTIPLIER,
    MAX_PAYOUT,
    MAX_STEPS,
    MAX_WAGER,
    MIN_STEP_MULTIPLIER,
    MIN_WAGER,
    RANKS,
    SUITS,
    WAGER_QUICK_AMOUNTS,
)
from .models import HiLoRound, HiLoStep
from .serializers import (
    HiLoHistoryItemSerializer,
    HiLoPlayRequestSerializer,
    HiLoPredictRequestSerializer,
    HiLoRoundSerializer,
    HiLoStepSerializer,
)
from .services import (
    ActiveRoundExists,
    HiLoGameUnavailable,
    ImpossiblePrediction,
    NoActiveRound,
    NothingToCashOut,
    RoundAlreadyResolved,
    StaleStep,
    cash_out,
    get_current_round,
    predict,
    start_round,
)


def _player_only(request):
    return getattr(request.user, 'user_type', None) == 'player'


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def config_view(request):
    return Response({
        'enabled': True,
        'game_version': GAME_VERSION,
        # Decimal fields serialize as strings - Number() before arithmetic.
        'min_wager': str(MIN_WAGER),
        'max_wager': str(MAX_WAGER),
        'wager_quick_amounts': WAGER_QUICK_AMOUNTS,
        'max_multiplier': str(MAX_MULTIPLIER),
        'max_payout': str(MAX_PAYOUT),
        'max_steps': MAX_STEPS,
        # The odds formula is not secret (nothing about a Hi-Lo round is -
        # the next card doesn't exist until it's requested), so the client
        # can render the same quote locally with these and stay in step
        # with the server between requests.
        'house_edge': str(HOUSE_EDGE),
        'min_step_multiplier': str(MIN_STEP_MULTIPLIER),
        'ranks': RANKS,
        'suits': SUITS,
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def play_view(request):
    if not _player_only(request):
        return Response({'error': 'Only players can play Rollin Hi-Lo.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = HiLoPlayRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        round_obj, created = start_round(
            request.user,
            wager_amount=data['wager_amount'],
            client_request_id=data.get('client_request_id', ''),
        )
    except HiLoGameUnavailable:
        return Response({'error': 'Rollin Hi-Lo is currently unavailable.'}, status=status.HTTP_400_BAD_REQUEST)
    except InsufficientPoints:
        return Response({'error': 'You do not have enough Reward Points for this play.'}, status=status.HTTP_400_BAD_REQUEST)
    except ActiveRoundExists as exc:
        return Response(
            {
                'error': 'You already have an active Rollin Hi-Lo round in progress.',
                'active_round': HiLoRoundSerializer(exc.round_obj).data,
            },
            status=status.HTTP_409_CONFLICT,
        )

    return Response(
        HiLoRoundSerializer(round_obj).data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def current_round_view(request):
    """
    Called once on mount to restore an in-flight round after a refresh.
    Not polled - a Hi-Lo round only changes when the player acts, so there
    is nothing to poll for. Returns null when there's nothing active.
    """
    round_obj = get_current_round(request.user)
    if not round_obj:
        return Response(None)
    return Response(HiLoRoundSerializer(round_obj).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def predict_view(request):
    serializer = HiLoPredictRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        round_obj, step = predict(
            request.user,
            direction=data['prediction'],
            step_index=data['step_index'],
        )
    except NoActiveRound:
        return Response({'error': 'No active Rollin Hi-Lo round.'}, status=status.HTTP_400_BAD_REQUEST)
    except RoundAlreadyResolved as exc:
        return Response(
            {
                'error': 'This round has already ended.',
                'round': HiLoRoundSerializer(exc.round_obj).data,
            },
            status=status.HTTP_409_CONFLICT,
        )
    except StaleStep as exc:
        # A duplicate click or a retried request, not a player error - the
        # prediction it names was already resolved. Hand back the
        # authoritative round (and the step that actually resolved it) so
        # the client can re-sync instead of showing a failure.
        last_step = exc.round_obj.steps.order_by('-step_index').first()
        return Response(
            {
                'error': 'That prediction was already resolved.',
                'round': HiLoRoundSerializer(exc.round_obj).data,
                'step': HiLoStepSerializer(last_step).data if last_step else None,
            },
            status=status.HTTP_409_CONFLICT,
        )
    except ImpossiblePrediction as exc:
        return Response(
            {'error': f'{exc.direction.capitalize()} is not possible from this card.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response({
        'step': HiLoStepSerializer(step).data,
        'round': HiLoRoundSerializer(round_obj).data,
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def cashout_view(request):
    try:
        round_obj = cash_out(request.user)
    except NoActiveRound:
        return Response({'error': 'No active Rollin Hi-Lo round to cash out.'}, status=status.HTTP_400_BAD_REQUEST)
    except NothingToCashOut:
        return Response(
            {'error': 'Make a correct prediction before cashing out.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except RoundAlreadyResolved as exc:
        # Duplicate Cash Out click - return the authoritative final state,
        # same shape as a fresh cash-out. Idempotent, matching Rocket.
        return Response(HiLoRoundSerializer(exc.round_obj).data, status=status.HTTP_200_OK)

    return Response(HiLoRoundSerializer(round_obj).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def history_view(request):
    rounds = (
        HiLoRound.objects
        .filter(
            user=request.user,
            status__in=[HiLoRound.STATUS_CASHED_OUT, HiLoRound.STATUS_BUSTED],
        )
        .prefetch_related('steps')[:HISTORY_LIMIT]
    )
    return Response(HiLoHistoryItemSerializer(rounds, many=True).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def stats_view(request):
    """
    The design spec's personal stats panel. Aggregated live over the round
    and step tables (no cached counters anywhere) - HiLoStep exists exactly
    so these are ordinary queries rather than new bookkeeping.
    """
    rounds = HiLoRound.objects.filter(user=request.user)
    resolved = rounds.filter(status__in=[HiLoRound.STATUS_CASHED_OUT, HiLoRound.STATUS_BUSTED])
    steps = HiLoStep.objects.filter(round__user=request.user)

    round_totals = resolved.aggregate(
        rounds_played=Count('id'),
        wagered=Sum('wager_amount'),
        won=Sum('payout_amount'),
        longest_streak=Max('streak'),
        highest_multiplier=Max('multiplier', filter=Q(status=HiLoRound.STATUS_CASHED_OUT)),
        highest_payout=Max('payout_amount'),
    )
    step_totals = steps.aggregate(
        predictions=Count('id'),
        correct=Count('id', filter=Q(outcome=HiLoStep.OUTCOME_WIN)),
        incorrect=Count('id', filter=Q(outcome=HiLoStep.OUTCOME_LOSS)),
        pushes=Count('id', filter=Q(outcome=HiLoStep.OUTCOME_PUSH)),
    )

    zero = Decimal('0.00')
    return Response({
        'rounds_played': round_totals['rounds_played'] or 0,
        'total_predictions': step_totals['predictions'] or 0,
        'correct_predictions': step_totals['correct'] or 0,
        'incorrect_predictions': step_totals['incorrect'] or 0,
        'pushes': step_totals['pushes'] or 0,
        'longest_streak': round_totals['longest_streak'] or 0,
        'highest_multiplier': str(round_totals['highest_multiplier'] or zero),
        'highest_payout': str(round_totals['highest_payout'] or zero),
        'total_wagered': str(round_totals['wagered'] or zero),
        'total_won': str(round_totals['won'] or zero),
    })
