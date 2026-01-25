from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, Max
from django.db.models.functions import Coalesce
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
            # CRITICAL: Unassign staff from all open chats to allow handover
            Room.objects.filter(current_handler=user, status='OPEN').update(current_handler=None)
            
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
    Staff users see all OPEN rooms in their queue.
    Players and agents see only their own room (creating it if needed).
    """
    user = request.user
    
    if user.user_type == 'staff':
        # Get staff's active support room to filter chats
        try:
            active_support_room = user.active_support_room
        except SupportRoom.DoesNotExist:
            return Response([], status=status.HTTP_200_OK)

        # Filter by QUEUE (Load Balancer)
        base_query = Room.objects.filter(status='OPEN', queue=active_support_room)
            
        rooms = base_query.annotate(
            unread_count=Count(
                'messages',
                filter=Q(messages__is_read=False) & ~Q(messages__sender=user)
            ),
            last_activity=Coalesce(Max('messages__timestamp'), 'created_at')
        ).order_by('-status', '-unread_count', '-last_activity')
    else:
        # Players and Agents get their single unique room
        room, created = Room.objects.get_or_create(
            client=user,
            defaults={'status': 'OPEN'}
        )
        
        # Load Balancing / Routing Logic
        # Check if queue needs assignment OR Re-assignment (Dynamic Re-routing)
        needs_routing = False
        if not room.queue:
            needs_routing = True
        elif not room.queue.is_active:
             # Queue is inactive (staff left), re-route to an active one!
             needs_routing = True
             
        if needs_routing:
            # Find candidate rooms
            candidates = SupportRoom.objects.filter(is_active=True)
            if user.user_type == 'player':
                candidates = candidates.filter(room_type__in=['player', 'all'])
            elif user.user_type == 'agent':
                candidates = candidates.filter(room_type__in=['agent', 'all'])
            
            # Annotate with load (OPEN queued chats)
            candidates = candidates.annotate(
                load=Count('queued_chats', filter=Q(queued_chats__status='OPEN'))
            ).order_by('load')
            
            if candidates.exists():
                room.queue = candidates.first()
                room.save()

        # If it was CLOSED, reopen it?
        if room.status == 'CLOSED':
            room.status = 'OPEN'
            # Re-route if queue became inactive? 
            # Ideally yes, but simpler to keep sticky for now unless explicitly requested.
            # If queue is inactive, maybe re-route?
            # Let's keep it sticky for "Permanent assignment" per user request.
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
        
    # Staff can only see rooms in their active queue
    if request.user.user_type == 'staff':
        try:
             active_support_room = request.user.active_support_room
             if room.queue and room.queue != active_support_room:
                 return Response({'error': 'Room not in your queue'}, status=status.HTTP_403_FORBIDDEN)
        except SupportRoom.DoesNotExist:
             return Response({'error': 'You are not in a support room'}, status=status.HTTP_403_FORBIDDEN)
        
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

    # Staff can only see rooms in their active queue
    if request.user.user_type == 'staff':
        try:
             active_support_room = request.user.active_support_room
             if room.queue and room.queue != active_support_room:
                 return Response({'error': 'Room not in your queue'}, status=status.HTTP_403_FORBIDDEN)
        except SupportRoom.DoesNotExist:
             return Response({'error': 'You are not in a support room'}, status=status.HTTP_403_FORBIDDEN)

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
        
    # Staff can only upload to rooms in their active queue
    if user.user_type == 'staff':
        try:
             active_support_room = user.active_support_room
             if room.queue != active_support_room:
                 return Response({'error': 'Room not in your queue'}, status=status.HTTP_403_FORBIDDEN)
        except SupportRoom.DoesNotExist:
             return Response({'error': 'You are not in a support room'}, status=status.HTTP_403_FORBIDDEN)

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
    For staff, this assigns 'current_handler' if empty.
    """
    room = get_object_or_404(Room, id=room_id)
    user = request.user
    
    # Permission check
    if user.user_type != 'staff' and room.client != user:
        return Response({'error': 'Not authorized to join this room'}, status=status.HTTP_403_FORBIDDEN)
    
    # If staff joins:
    if user.user_type == 'staff':
        # If open but no current handler, claim it
        if not room.current_handler:
            room.current_handler = user
            room.save()
        # If already handled by someone else, we just join as a participant (viewing/assisting)
        # Requirement: "Allow the new staff to reply seamlessly as continuation."

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
         
    # Optional: Enforce only current handler can close?
    # if room.current_handler != user:
    #    return Response({'error': 'You are not the current handler'}, status=status.HTTP_403_FORBIDDEN)
        
    room.status = 'CLOSED'
    room.current_handler = None # Clear handler on close logic
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
    try:
        active_support_room = user.active_support_room
        room_type = active_support_room.room_type
    except SupportRoom.DoesNotExist:
        room_type = None

    base_query = Room.objects.filter(status='OPEN')
    
    if room_type:
        if room_type == 'player':
            base_query = base_query.filter(client__user_type='player')
        elif room_type == 'agent':
            base_query = base_query.filter(client__user_type='agent')
    else:
        # Fallback: only show rooms explicitly assigned if not in a support station
        base_query = base_query.filter(current_handler=user)
    
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
