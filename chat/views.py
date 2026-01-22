from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .models import Room, Message, RoomParticipant, SupportRoom
from .serializers import (
    RoomSerializer,
    RoomDetailSerializer,
    MessageSerializer,
    RoomParticipantSerializer,
    SupportRoomSerializer
)
from django.contrib.auth import get_user_model
User = get_user_model()


class SupportRoomViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Support Rooms (Workstations).
    """
    queryset = SupportRoom.objects.all()
    serializer_class = SupportRoomSerializer
    permission_classes = [IsAuthenticated]
    
    @action(detail=True, methods=['post'])
    def enter(self, request, pk=None):
        room = self.get_object()
        user = request.user
        
        if user.user_type != 'staff':
            return Response({'error': 'Only staff can enter support rooms'}, status=status.HTTP_403_FORBIDDEN)
            
        if room.staff and room.staff != user:
            return Response({'error': 'Room is occupied'}, status=status.HTTP_400_BAD_REQUEST)
            
        # Check if user is already in another room
        if SupportRoom.objects.filter(staff=user).exclude(id=room.id).exists():
           return Response({'error': 'You are already in another support room'}, status=status.HTTP_400_BAD_REQUEST)

        room.staff = user
        room.is_active = True
        room.save()
        
        return Response({'status': 'entered', 'room': SupportRoomSerializer(room).data})

    @action(detail=True, methods=['post'])
    def leave(self, request, pk=None):
        room = self.get_object()
        user = request.user
        
        if room.staff == user:
            room.staff = None
            room.is_active = False
            room.save()
            return Response({'status': 'left'})
            
        return Response({'error': 'You are not in this room'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def room_list_view(request):
    """
    Get list of available rooms.
    Staff users see all active client rooms.
    Players and agents see only their own room (creating it if needed).
    """
    user = request.user
    
    if user.user_type == 'staff':
        # Staff sees all rooms (active for assigned, inactive for unassigned/pending)
        # Ordered by status (active first) then creation date
        rooms = Room.objects.all().order_by('-is_active', '-created_at')
    else:
        # Players and Agents get their single unique room
        # Get or create logic
        room, created = Room.objects.get_or_create(
            client=user,
            defaults={'is_active': True}
        )
        
        # If created or currently unassigned, try to assign to an active staff member
        if not room.staff_assigned:
            # Find active support room with least load
            # We look for staff in active SupportRooms
            # Then we count how many active Rooms (chats) they are already assigned to
            from django.db.models import Count, Q
            
            # Get staff active in support rooms
            # Annotate with the count of their CURRENTLY ACTIVE assigned chat rooms
            active_staff = User.objects.filter(
                active_support_room__is_active=True
            ).annotate(
                active_chat_count=Count('assigned_rooms', filter=Q(assigned_rooms__is_active=True))
            ).order_by('active_chat_count')
            
            if active_staff.exists():
                # Pick the one with the least active chats
                selected_staff = active_staff.first()
                room.staff_assigned = selected_staff
                room.save()

        # If it was inactive, reactivate it? Or keep as is.
        # Assuming one active room concept.
        if not room.is_active:
            room.is_active = True
            room.save()
            
        rooms = [room]
    
    serializer = RoomSerializer(rooms, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def room_detail_view(request, room_id):
    """
    Get detailed information about a specific room.
    """
    room = get_object_or_404(Room, id=room_id)
    
    # Permission check
    if request.user.user_type != 'staff' and room.client != request.user:
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        
    serializer = RoomDetailSerializer(room)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def room_messages_view(request, room_id):
    """
    Get message history for a room.
    """
    room = get_object_or_404(Room, id=room_id)
    
     # Permission check
    if request.user.user_type != 'staff' and room.client != request.user:
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    messages = Message.objects.filter(room=room).order_by('-timestamp')[:100]
    messages = list(reversed(messages))  # Reverse to show oldest first
    serializer = MessageSerializer(messages, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def join_room_view(request, room_id):
    """
    Join a room.
    For clients, this is just a check/confirmation.
    For staff, this might mark them as 'viewing'.
    """
    room = get_object_or_404(Room, id=room_id)
    user = request.user
    
    # Permission check
    if user.user_type != 'staff' and room.client != user:
        return Response({'error': 'Not authorized to join this room'}, status=status.HTTP_403_FORBIDDEN)
    
    # If staff joins an unassigned room, assign it to them
    if user.user_type == 'staff' and not room.staff_assigned:
        room.staff_assigned = user
        room.is_active = True
        room.save()

    participant, created = RoomParticipant.objects.get_or_create(
        room=room,
        user=user
    )
    participant.is_active = True
    participant.save()
    
    serializer = RoomParticipantSerializer(participant)
    return Response(
        {
            'message': 'Joined room successfully',
            'participant': serializer.data
        },
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def close_room_view(request, room_id):
    """
    Close a room (resolve the ticket).
    Only assigned staff can close the room.
    """
    room = get_object_or_404(Room, id=room_id)
    user = request.user
    
    if user.user_type != 'staff':
         return Response({'error': 'Only staff can close rooms'}, status=status.HTTP_403_FORBIDDEN)
         
    if room.staff_assigned != user:
        return Response({'error': 'You are not assigned to this room'}, status=status.HTTP_403_FORBIDDEN)
        
    room.is_active = False
    room.save()
    
    return Response({'status': 'closed', 'message': 'Chat resolved'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def staff_dashboard_view(request):
    """
    Staff dashboard view.
    Returns general stats.
    """
    user = request.user
    
    if user.user_type != 'staff':
        return Response(
            {'error': 'Access denied. Staff only.'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Global stats for this staff member or all?
    # Let's show stats for rooms they are assigned to, or just general stats
    
    assigned_rooms = Room.objects.filter(staff_assigned=user, is_active=True)
    
    total_participants = RoomParticipant.objects.filter(room__in=assigned_rooms, is_active=True).count()
    total_messages = Message.objects.filter(room__in=assigned_rooms).count()
    
    # Recent messages from across all assigned rooms
    recent_messages = Message.objects.filter(room__in=assigned_rooms).order_by('-timestamp')[:10]
    
    return Response({
        'room': None, # No single room concept anymore, maybe list?
        'statistics': {
            'total_participants': total_participants,
            'total_messages': total_messages,
            'assigned_rooms_count': assigned_rooms.count()
        },
        'recent_messages': MessageSerializer(recent_messages, many=True).data
    }, status=status.HTTP_200_OK)
