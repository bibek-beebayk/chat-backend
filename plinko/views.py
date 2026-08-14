from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from points.services import InsufficientPoints
from .constants import MULTIPLIER_TABLES, RISK_CHOICES, ROWS_CHOICES, WAGER_OPTIONS
from .free_drop_constants import FREE_DROP_MULTIPLIER_TABLES, FREE_DROP_ROWS_CHOICES
from .free_drop_services import play_free_drop_round
from .models import PlinkoRound
from .serializers import (
    FreeDropPlayRequestSerializer,
    PlinkoPlayRequestSerializer,
    PlinkoRoundSerializer,
)
from .services import GameUnavailable, play_round


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def config_view(request):
    return Response({
        'rows_options': list(ROWS_CHOICES),
        'risk_options': list(RISK_CHOICES),
        'multipliers': MULTIPLIER_TABLES,
        'wager_options': list(WAGER_OPTIONS),
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def play_view(request):
    if getattr(request.user, 'user_type', None) != 'player':
        return Response({'error': 'Only players can play Plinko.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = PlinkoPlayRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        round_obj = play_round(
            request.user,
            rows=serializer.validated_data['rows'],
            risk_level=serializer.validated_data['risk_level'],
            wager_amount=serializer.validated_data['wager_amount'],
            drop_offset=serializer.validated_data['drop_offset'],
        )
    except GameUnavailable:
        return Response({'error': 'Plinko is currently unavailable.'}, status=status.HTTP_400_BAD_REQUEST)
    except InsufficientPoints:
        return Response({'error': 'You do not have enough points for this wager.'}, status=status.HTTP_400_BAD_REQUEST)

    return Response(PlinkoRoundSerializer(round_obj).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def history_view(request):
    rounds = PlinkoRound.objects.filter(user=request.user)[:50]
    return Response(PlinkoRoundSerializer(rounds, many=True).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def free_drop_config_view(request):
    return Response({
        'rows_options': list(FREE_DROP_ROWS_CHOICES),
        'risk_options': list(RISK_CHOICES),
        'multipliers': FREE_DROP_MULTIPLIER_TABLES,
        'wager_options': list(WAGER_OPTIONS),
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def free_drop_play_view(request):
    if getattr(request.user, 'user_type', None) != 'player':
        return Response({'error': 'Only players can play Plinko.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = FreeDropPlayRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        round_obj = play_free_drop_round(
            request.user,
            rows=serializer.validated_data['rows'],
            risk_level=serializer.validated_data['risk_level'],
            wager_amount=serializer.validated_data['wager_amount'],
            drop_position=serializer.validated_data['drop_position'],
        )
    except GameUnavailable:
        return Response({'error': 'Plinko is currently unavailable.'}, status=status.HTTP_400_BAD_REQUEST)
    except InsufficientPoints:
        return Response({'error': 'You do not have enough points for this wager.'}, status=status.HTTP_400_BAD_REQUEST)

    return Response(PlinkoRoundSerializer(round_obj).data, status=status.HTTP_201_CREATED)
