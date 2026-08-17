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
