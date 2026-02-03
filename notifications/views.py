from rest_framework import viewsets, mixins, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import PushToken
from .serializers import PushTokenSerializer

class PushTokenViewSet(viewsets.GenericViewSet, mixins.CreateModelMixin):
    serializer_class = PushTokenSerializer
    permission_classes = [IsAuthenticated]
    
    def create(self, request, *args, **kwargs):
        # We use create to Register or Update the token
        fcm_token = request.data.get('fcm_token')
        if not fcm_token:
            return Response({'error': 'fcm_token required'}, status=status.HTTP_400_BAD_REQUEST)
            
        # Update or Create
        token, created = PushToken.objects.update_or_create(
            user=request.user,
            fcm_token=fcm_token,
            defaults={
                'device': request.data.get('device', ''),
                'browser': request.data.get('browser', ''),
                'is_active': True
            }
        )
        
        return Response({'status': 'registered', 'id': token.id}, status=status.HTTP_201_CREATED)
