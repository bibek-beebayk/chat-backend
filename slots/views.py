from django.db import IntegrityError
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from points.services import InsufficientPoints
from .constants import (
    GAME_VERSION,
    MAX_WAGER,
    MIN_WAGER,
    PAYLINES,
    PAYTABLE,
    REEL_STRIPS,
    SYMBOL_LABELS,
    SYMBOLS,
    WAGER_PRESETS,
)
from .models import SlotRound
from .serializers import SlotPlayRequestSerializer, SlotRoundSerializer
from .services import SlotGameUnavailable, play_round


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def config_view(request):
    return Response({
        'enabled': True,
        'game_version': GAME_VERSION,
        'min_wager': MIN_WAGER,
        'max_wager': MAX_WAGER,
        'wager_presets': WAGER_PRESETS,
        'symbols': [{'id': symbol, 'label': SYMBOL_LABELS[symbol]} for symbol in SYMBOLS],
        'paytable': {symbol: str(multiplier) for symbol, multiplier in PAYTABLE.items()},
        'paylines': PAYLINES,
        # Exposing the strip *order* is safe - it never reveals which stop
        # the server will pick (a fresh secrets.SystemRandom() draw per
        # spin), only lets the frontend animate through the real strip
        # instead of faking symbols and swapping in the authoritative grid
        # at the last moment (see FINAL V1 REQUIREMENT: natural animation).
        'reel_strips': REEL_STRIPS,
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def play_view(request):
    if getattr(request.user, 'user_type', None) != 'player':
        return Response({'error': 'Only players can play the Rollin 3x3 slot.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = SlotPlayRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    client_request_id = serializer.validated_data.get('client_request_id', '')

    try:
        round_obj, created = play_round(
            request.user,
            wager_amount=serializer.validated_data['wager'],
            client_request_id=client_request_id,
        )
    except SlotGameUnavailable:
        return Response({'error': 'The Rollin 3x3 slot is currently unavailable.'}, status=status.HTTP_400_BAD_REQUEST)
    except InsufficientPoints:
        return Response({'error': 'You do not have enough Reward Points for this wager.'}, status=status.HTTP_400_BAD_REQUEST)
    except IntegrityError:
        # Lost a genuine concurrent race on the same client_request_id (see
        # slots.services.play_round) - the winner's round is authoritative.
        round_obj = SlotRound.objects.filter(user=request.user, client_request_id=client_request_id).first()
        if not round_obj:
            raise
        created = False

    return Response(SlotRoundSerializer(round_obj).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def history_view(request):
    rounds = SlotRound.objects.filter(user=request.user)[:50]
    return Response(SlotRoundSerializer(rounds, many=True).data)
