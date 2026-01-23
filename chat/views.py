from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count
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
        # Get staff's active support room to filter chats
        try:
            active_support_room = user.active_support_room
            room_type = active_support_room.room_type
        except SupportRoom.DoesNotExist:
            room_type = 'all'

        # Filter logic
        # If General Support ('all') or no room, show everything
        # If Player Support, show only player chats
        # If Agent Support, show only agent chats
        
        base_query = Room.objects.all()
        if room_type == 'player':
            base_query = base_query.filter(client__user_type='player')
        elif room_type == 'agent':
            base_query = base_query.filter(client__user_type='agent')
            
        rooms = base_query.annotate(
            unread_count=Count(
                'messages',
                filter=Q(messages__is_read=False) & ~Q(messages__sender=user)
            )
        ).order_by('-is_active', '-unread_count', '-created_at')
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
            
        # Manually annotate unread count for serializer compatibility
        room.unread_count = room.messages.filter(is_read=False).exclude(sender=user).count()
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
        
    serializer = RoomDetailSerializer(room, context={'request': request})
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

    # Mark unread messages as read
    Message.objects.filter(room=room, is_read=False).exclude(sender=request.user).update(is_read=True)

    messages = Message.objects.filter(room=room).order_by('-timestamp')[:100]
    messages = list(reversed(messages))  # Reverse to show oldest first
    serializer = MessageSerializer(messages, many=True, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_attachment_view(request, room_id):
    """
    Upload a file attachment to a chat room.
    """
    room = get_object_or_404(Room, id=room_id)
    user = request.user
    
    # Permission check
    if user.user_type != 'staff' and room.client != user:
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

    # Create Message with attachment
    # Note: Content is optional if we have an attachment, but good to have a fallback text
    content = request.data.get('content', '')
    if not content:
        content = f"Sent a file: {file_obj.name}"

    message = Message.objects.create(
        room=room,
        sender=user,
        content=content,
        attachment=file_obj
    )

    # Broadcast via WebSocket
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    
    channel_layer = get_channel_layer()
    room_group_name = f'chat_{room_id}'
    
    # Construct attachment URL manually if needed, or rely on serializer
    # Serializer 'attachment' field will provide the full URL if context is passed, 
    # but here we are in a view, so we can use the serializer.
    
    msg_data = MessageSerializer(message, context={'request': request}).data
    
    async_to_sync(channel_layer.group_send)(
        room_group_name,
        {
            'type': 'chat_message',
            'message': message.content,
            'username': user.username,
            'user_id': user.id,
            'message_id': message.id,
            'timestamp': message.timestamp.isoformat(),
            'attachment': msg_data['attachment'] 
        }
    )

    return Response(msg_data, status=status.HTTP_201_CREATED)


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
    Returns general stats for the current support queue.
    """
    user = request.user
    
    if user.user_type != 'staff':
        return Response(
            {'error': 'Access denied. Staff only.'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Determine scope based on available support room
    # If staff is in 'Player Support', show all player rooms
    try:
        active_support_room = user.active_support_room
        room_type = active_support_room.room_type
    except SupportRoom.DoesNotExist:
        room_type = None

    base_query = Room.objects.filter(is_active=True)
    
    if room_type:
        if room_type == 'player':
            base_query = base_query.filter(client__user_type='player')
        elif room_type == 'agent':
            base_query = base_query.filter(client__user_type='agent')
        # 'all' implies no filter on client type
    else:
        # Fallback: only show rooms explicitly assigned if not in a support station
        base_query = base_query.filter(staff_assigned=user)
    
    relevant_rooms = base_query
    
    total_participants = RoomParticipant.objects.filter(room__in=relevant_rooms, is_active=True).count()
    total_messages = Message.objects.filter(room__in=relevant_rooms).count()
    
    # Recent messages from across all relevant rooms
    recent_messages = Message.objects.filter(room__in=relevant_rooms).order_by('-timestamp')[:10]
    
    return Response({
        'room': None, 
        'statistics': {
            'total_participants': total_participants,
            'total_messages': total_messages,
            'assigned_rooms_count': relevant_rooms.count()
        },
        'recent_messages': MessageSerializer(recent_messages, many=True, context={'request': request}).data
    }, status=status.HTTP_200_OK)
