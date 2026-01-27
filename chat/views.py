from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from django.utils import timezone
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
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

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
            # Maybe allow "hijacking" or just joining? 
            # For now, if occupied by someone else, return error.
            return Response({'error': 'Room is occupied'}, status=status.HTTP_400_BAD_REQUEST)
            
        # Removed "already in another room" check to allow multi-room
        # if SupportRoom.objects.filter(staff=user).exclude(id=room.id).exists():
        #    return Response({'error': 'You are already in another support room'}, status=status.HTTP_400_BAD_REQUEST)

        room.staff = user
        room.is_active = True
        room.save()
        
        return Response({'status': 'entered', 'room': SupportRoomSerializer(room).data})

    @action(detail=True, methods=['post'])
    def leave(self, request, pk=None):
        room = self.get_object()
        user = request.user
        
        if room.staff == user:
            # CRITICAL: Unassign staff from open chats IN THIS QUEUE ONLY
            Room.objects.filter(current_handler=user, status='OPEN', queue=room).update(current_handler=None)
            
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
        # Get staff's active support roomS to filter chats
        # Changed: fetch all active rooms
        active_support_rooms = user.active_support_rooms.all()
        if not active_support_rooms.exists():
            return Response([], status=status.HTTP_200_OK)

        # Filter by QUEUE (Load Balancer) - ANY of the active queues
        base_query = Room.objects.filter(status='OPEN', queue__in=active_support_rooms)
            
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
        active_support_rooms = request.user.active_support_rooms.all()
        if not active_support_rooms.exists():
            return Response({'error': 'You are not in a support room'}, status=status.HTTP_403_FORBIDDEN)

        if room.queue and room.queue not in active_support_rooms:
            return Response({'error': 'Room not in your queues'}, status=status.HTTP_403_FORBIDDEN)
        
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
        active_support_rooms = request.user.active_support_rooms.all()
        if not active_support_rooms.exists():
            return Response({'error': 'You are not in a support room'}, status=status.HTTP_403_FORBIDDEN)

        if room.queue and room.queue not in active_support_rooms:
            return Response({'error': 'Room not in your queues'}, status=status.HTTP_403_FORBIDDEN)

    # Mark unread messages as read
    Message.objects.filter(room=room, is_read=False).exclude(sender=request.user).update(is_read=True)

    # Infinite Scroll / Pagination Logic
    before_id = request.query_params.get('before_id')
    after_id = request.query_params.get('after_id')
    around_id = request.query_params.get('around_id')
    limit = int(request.query_params.get('limit', 20))
    
    messages_query = Message.objects.filter(room=room).order_by('-timestamp')
    
    if around_id:
        # Fetch context around a message
        # We try to get limit/2 before and limit/2 after
        try:
            target_msg = Message.objects.get(id=around_id, room=room)
            
            # Context before (older)
            older = list(Message.objects.filter(
                room=room, 
                timestamp__lte=target_msg.timestamp
            ).exclude(id=target_msg.id).order_by('-timestamp')[:limit//2])
            
            # Context after (newer)
            newer = list(Message.objects.filter(
                room=room, 
                timestamp__gte=target_msg.timestamp
            ).exclude(id=target_msg.id).order_by('timestamp')[:limit//2])
            
            # Combine: older(reversed) + target + newer
            messages = list(reversed(older)) + [target_msg] + newer
            
            # Since we manually built the list, no need to query further
        except Message.DoesNotExist:
             return Response({'error': 'Message not found'}, status=status.HTTP_404_NOT_FOUND)

    elif after_id:
        # Fetch newer messages (Scroll Down)
        # Note: We order by timestamp ASC here to get the immediate next messages
        messages = list(Message.objects.filter(
            room=room, 
            id__gt=after_id
        ).order_by('timestamp')[:limit])
        
    elif before_id:
        # Fetch older messages (Scroll Up)
        messages = list(Message.objects.filter(
            room=room, 
            id__lt=before_id
        ).order_by('-timestamp')[:limit])
        messages = list(reversed(messages)) # Show oldest first
        
    else:
        # Default: Latest messages
        messages = list(messages_query[:limit])
        messages = list(reversed(messages)) # Show oldest first
    
    serializer = MessageSerializer(messages, many=True, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pinned_messages_view(request, room_id):
    """
    Get (all) pinned messages for a room.
    """
    room = get_object_or_404(Room, id=room_id)
    
    # Permission check (same as room_messages_view)
    if request.user.user_type != 'staff' and room.client != request.user:
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    if request.user.user_type == 'staff':
        active_support_rooms = request.user.active_support_rooms.all()
        if not active_support_rooms.exists():
             return Response({'error': 'You are not in a support room'}, status=status.HTTP_403_FORBIDDEN)
             
        if room.queue and room.queue not in active_support_rooms:
             return Response({'error': 'Room not in your queues'}, status=status.HTTP_403_FORBIDDEN)

    messages = Message.objects.filter(room=room, is_pinned=True, is_deleted=False).order_by('timestamp')
    serializer = MessageSerializer(messages, many=True)
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
        active_support_rooms = user.active_support_rooms.all()
        if not active_support_rooms.exists():
             return Response({'error': 'You are not in a support room'}, status=status.HTTP_403_FORBIDDEN)

        if room.queue and room.queue not in active_support_rooms:
             return Response({'error': 'Room not in your queues'}, status=status.HTTP_403_FORBIDDEN)

    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

    # Create Message with attachment
    # Content is optional if we have an attachment. We leave it empty if not provided.
    content = request.data.get('content', '')
    
    message = Message.objects.create(
        room=room,
        sender=user,
        content=content,
        attachment=file_obj
    )

    # Broadcast via WebSocket
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


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def edit_message(request, message_id):
    message = get_object_or_404(Message, id=message_id)
    
    # Permission check: Only sender can edit, or maybe staff can edit all?
    # Let's say only sender for now.
    if message.sender != request.user:
         return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    new_content = request.data.get('content')
    if new_content is not None:
        message.content = new_content
        message.is_edited = True
        message.edited_at = timezone.now()
        message.save()

        # Broadcast update
        channel_layer = get_channel_layer()
        room_group_name = f'chat_{message.room.id}'
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'chat_message_update', 
                'id': message.id,
                'content': message.content,
                'is_edited': True,
                'edited_at': message.edited_at.isoformat()
            }
        )
        
        return Response(MessageSerializer(message, context={'request': request}).data)
    return Response({'error': 'No content provided'}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_message(request, message_id):
    message = get_object_or_404(Message, id=message_id)
    
    if message.sender != request.user:
         return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    # Soft delete
    message.is_deleted = True
    message.content = "This message was deleted."
    message.attachment = None # Remove attachment on delete
    message.save()

    # Broadcast update
    channel_layer = get_channel_layer()
    room_group_name = f'chat_{message.room.id}'
    async_to_sync(channel_layer.group_send)(
        room_group_name,
        {
            'type': 'chat_message_delete', 
            'id': message.id,
            'is_deleted': True
        }
    )
    return Response({'status': 'deleted'})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pin_message(request, message_id):
    message = get_object_or_404(Message, id=message_id)
    
    # Any participant can pin? Or just staff? Let's allow any participant for now.
    # Check if user is in room
    is_staff = request.user.user_type == 'staff'
    is_room_client = message.room.client == request.user
    
    if not (is_staff or is_room_client):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        
    message.is_pinned = not message.is_pinned
    message.save()

    # Broadcast update
    channel_layer = get_channel_layer()
    room_group_name = f'chat_{message.room.id}'
    async_to_sync(channel_layer.group_send)(
        room_group_name,
        {
            'type': 'chat_message_pin',
            'id': message.id,
            'is_pinned': message.is_pinned
        }
    )
    
    return Response({'status': 'pinned', 'is_pinned': message.is_pinned})


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
    active_support_rooms = user.active_support_rooms.all()
    room_types = [room.room_type for room in active_support_rooms]

    if not active_support_rooms.exists():
        room_types = []

    base_query = Room.objects.filter(status='OPEN')
    
    if room_types:
        # Filter where room type matches ANY of the active room types
        # Note: This is simplified. If I am in "Player Support Room A" and "Agent Support Room B",
        # I should see player chats queues in A and agent chats queued in B.
        # But our room_list logic already filters by queue.
        # Dashboard wants "stats". Let's stats for ALL active rooms.
        # We can just filter by queue__in=active_support_rooms
        base_query = base_query.filter(queue__in=active_support_rooms)
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

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def switch_station_view(request):
    """
    Allows a client (player/agent) to switch their support station (queue)
    to another active station of the same type.
    """
    user = request.user
    if user.user_type == 'staff':
        return Response({'error': 'Staff cannot switch stations this way'}, status=status.HTTP_400_BAD_REQUEST)

    # Get user's room
    try:
        room = Room.objects.get(client=user)
    except Room.DoesNotExist:
        return Response({'error': 'No active chat room found'}, status=status.HTTP_404_NOT_FOUND)

    current_queue = room.queue
    if not current_queue:
        return Response({'error': 'You are not assigned to a station'}, status=status.HTTP_400_BAD_REQUEST)

    # Find alternative ACTIVE stations of the same type
    # Must be active (staff assigned) and not the current one
    alternatives = SupportRoom.objects.filter(
        room_type=current_queue.room_type,
        is_active=True,
        staff__isnull=False
    ).exclude(id=current_queue.id)

    if not alternatives.exists():
        return Response({'error': 'No other support stations are currently available'}, status=status.HTTP_404_NOT_FOUND)

    # Pick one (randomly or first)
    # Simple logic: just pick the first one for now, or random
    import random
    new_queue = random.choice(list(alternatives))

    # Re-assign
    room.queue = new_queue
    # clear current handler if any, so new staff sees it as fresh? 
    # Or keep it? Usually if switching station, you want a new handler.
    room.current_handler = None 
    room.save()

    # Create a system message?
    Message.objects.create(
        room=room,
        sender=user, # Or system?
        content=f"System: Switched support station to {new_queue.name}",
        is_read=True
    )

    return Response({
        'status': 'switched',
        'new_station': new_queue.name,
        'message': f"You have been moved to {new_queue.name}"
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_email_view(request):
    """
    Test endpoint to send an email.
    """
    from chat_project.utils import send_zeptomail
    from django.conf import settings
    
    recipient = request.data.get('email', 'beebayk0001@gmail.com')
    
    try:
        send_zeptomail(
            recipient,
            'Test Email from HR Agent',
            """
            <html>
                <body>
                    <h2>Test Email</h2>
                    <p>This is a test email to verify SMTP configuration is working correctly.</p>
                    <p>Sent via ZeptoMail integration.</p>
                </body>
            </html>
            """
        )
        return Response({
            'status': 'success',
            'message': f'Test email sent successfully to {recipient}'
        })
    except Exception as e:
        return Response({
            'status': 'error',
            'message': f'Failed to send email: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
