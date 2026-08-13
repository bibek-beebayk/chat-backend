from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .models import Game
from .serializers import GameSerializer


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def game_list_view(request):
    games = Game.objects.filter(is_active=True)
    return Response(GameSerializer(games, many=True).data)
