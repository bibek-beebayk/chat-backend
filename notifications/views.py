from rest_framework import viewsets, mixins, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .models import Notification, PushToken
from .serializers import NotificationSerializer, PushTokenSerializer

class PushTokenViewSet(viewsets.GenericViewSet, mixins.CreateModelMixin):
    serializer_class = PushTokenSerializer
    permission_classes = [IsAuthenticated]
    
    def create(self, request, *args, **kwargs):
        # We use create to Register or Update the token
        fcm_token = request.data.get('fcm_token')
        if not fcm_token:
            return Response({'error': 'fcm_token required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Deactivate this token for any OTHER users (device changed accounts)
        PushToken.objects.filter(fcm_token=fcm_token).exclude(user=request.user).update(is_active=False)
            
        # Update or Create for the current user
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


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def notification_list_view(request):
    notifications = Notification.objects.filter(user=request.user)[:50]
    return Response(NotificationSerializer(notifications, many=True).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def notification_mark_read_view(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])
    return Response(NotificationSerializer(notification).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def notification_mark_all_read_view(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({'status': 'ok'})
