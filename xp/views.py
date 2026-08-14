from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .models import XPAction, XPBalance
from .serializers import XPActionSerializer, XPStatusSerializer


def _is_staff_user(user):
    return bool(user and user.is_authenticated and getattr(user, 'user_type', None) == 'staff')


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def status_view(request):
    balance, _ = XPBalance.objects.get_or_create(user=request.user)
    return Response(XPStatusSerializer(balance).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def action_list_view(request):
    if not _is_staff_user(request.user):
        return Response({'error': 'Only staff can view XP actions.'}, status=status.HTTP_403_FORBIDDEN)

    actions = XPAction.objects.all()
    return Response(XPActionSerializer(actions, many=True).data)
