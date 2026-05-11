from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, Max, Case, When, Value, IntegerField, Subquery, OuterRef
from django.db.models.functions import Coalesce
from django.db import transaction
from .models import (
    Room,
    Message,
    RoomParticipant,
    SupportRoom,
    AgentQuickReply,
    ChatInternalNote,
    GroupJoinRequest,
)
from .serializers import (
    RoomSerializer,
    RoomDetailSerializer,
    MessageSerializer,
    RoomParticipantSerializer,
    SupportRoomSerializer,
    AgentQuickReplySerializer,
    ChatInternalNoteSerializer,
    GroupJoinRequestSerializer,
)
from accounts.serializers import UserSerializer
from chat_project.url_utils import build_public_absolute_uri
from django.contrib.auth import get_user_model
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from social.models import UserConnection

User = get_user_model()

def _is_test_actor(user):
    return bool(getattr(user, 'is_test_user', False))

def _room_scope_match(room, user):
    return bool(room.is_test_room) == _is_test_actor(user)


def _can_non_staff_access_room(room, user):
    if room.room_type == 'support':
        return room.client_id == user.id
    if room.room_type == 'direct_agent':
        return room.participants.filter(user=user, is_active=True).exists()
    if room.room_type == 'group':
        return room.participants.filter(user=user, is_active=True).exists()
    return False


def _can_staff_access_room(room, user):
    if room.room_type in ('direct_agent', 'group'):
        return False
    return (
        room.current_handler_id == user.id
        or (room.queue_id is not None and user.active_support_rooms.filter(id=room.queue_id).exists())
        or room.participants.filter(user=user, is_active=True).exists()
    )


def _can_user_access_room(room, user):
    if user.user_type == 'staff':
        return _can_staff_access_room(room, user)
    return _can_non_staff_access_room(room, user)


def _ensure_direct_room_for_users(left_user, right_user):
    room, created = Room.objects.get_or_create(
        room_type='direct_agent',
        direct_player=left_user,
        direct_agent=right_user,
        defaults={
            'status': 'OPEN',
            'is_test_room': _is_test_actor(left_user),
            'name': f'direct_{left_user.username}_{right_user.username}',
        },
    )
    if room.status == 'CLOSED':
        room.status = 'OPEN'
        room.save(update_fields=['status'])

    left_participant, _ = RoomParticipant.objects.get_or_create(
        room=room,
        user=left_user,
        defaults={'is_active': True},
    )
    if not left_participant.is_active:
        left_participant.is_active = True
        left_participant.save(update_fields=['is_active'])

    right_participant, _ = RoomParticipant.objects.get_or_create(
        room=room,
        user=right_user,
        defaults={'is_active': True},
    )
    if not right_participant.is_active:
        right_participant.is_active = True
        right_participant.save(update_fields=['is_active'])

    return room, created


def _expected_connection_type_for_pair(left_user, right_user):
    if left_user.user_type == 'player' and right_user.user_type == 'player':
        return UserConnection.TYPE_PLAYER_PLAYER
    return UserConnection.TYPE_PLAYER_AGENT


def _has_accepted_connection(left_user, right_user):
    connection_type = _expected_connection_type_for_pair(left_user, right_user)
    return UserConnection.objects.filter(
        (
            Q(requester=left_user, receiver=right_user)
            | Q(requester=right_user, receiver=left_user)
        ),
        connection_type=connection_type,
        status=UserConnection.STATUS_ACCEPTED,
    ).exists()


def _sync_direct_request_state(room, initiator, counterpart):
    if room.room_type != 'direct_agent':
        return

    has_connection = _has_accepted_connection(initiator, counterpart)
    if has_connection:
        fields = []
        if room.direct_request_status != 'accepted':
            room.direct_request_status = 'accepted'
            fields.append('direct_request_status')
        if room.direct_request_initiator_id is not None:
            room.direct_request_initiator = None
            fields.append('direct_request_initiator')
        if fields:
            room.save(update_fields=fields)
        return

    # No accepted connection: keep this chat under message requests.
    fields = []
    if room.direct_request_status != 'pending':
        room.direct_request_status = 'pending'
        fields.append('direct_request_status')
    if room.direct_request_initiator_id is None:
        room.direct_request_initiator = initiator
        fields.append('direct_request_initiator')
    if fields:
        room.save(update_fields=fields)


class SupportRoomViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Support Rooms (Workstations).
    """
    queryset = SupportRoom.objects.all()
    serializer_class = SupportRoomSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SupportRoom.objects.filter(is_test_room=_is_test_actor(self.request.user))
    
    @action(detail=True, methods=['post'])
    def enter(self, request, pk=None):
        room = self.get_object()
        user = request.user
        
        if user.user_type != 'staff':
            return Response({'error': 'Only staff can enter support rooms'}, status=status.HTTP_403_FORBIDDEN)
        if room.is_test_room != _is_test_actor(user):
            return Response({'error': 'Not authorized for this support room scope'}, status=status.HTTP_403_FORBIDDEN)
            
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
        latest_sender_subquery = Message.objects.filter(
            room=OuterRef('pk')
        ).order_by('-timestamp').values('sender_id')[:1]
        # Get staff's active support roomS to filter chats
        # Changed: fetch all active rooms
        active_support_rooms = user.active_support_rooms.filter(is_test_room=_is_test_actor(user))
        if not active_support_rooms.exists():
            return Response([], status=status.HTTP_200_OK)

        # Filter by QUEUE (Load Balancer) - ANY of the active queues
        base_query = Room.objects.filter(
            status='OPEN',
            room_type='support',
            queue__in=active_support_rooms,
            is_test_room=_is_test_actor(user),
        )
            
        rooms = base_query.annotate(
            unread_count=Count(
                'messages',
                filter=Q(messages__is_read=False) & ~Q(messages__sender=user)
            ),
            last_activity=Coalesce(Max('messages__timestamp'), 'created_at'),
            last_message_sender_id=Subquery(latest_sender_subquery),
        ).order_by('-status', '-unread_count', '-last_activity')
    else:
        latest_sender_subquery = Message.objects.filter(
            room=OuterRef('pk')
        ).order_by('-timestamp').values('sender_id')[:1]
        rooms = []
        support_room, created = Room.objects.get_or_create(
            client=user,
            room_type='support',
            defaults={'status': 'OPEN', 'is_test_room': _is_test_actor(user)}
        )
        if support_room.is_test_room != _is_test_actor(user):
            support_room.is_test_room = _is_test_actor(user)
            support_room.queue = None
            support_room.current_handler = None
            support_room.save()

        needs_routing = False
        requested_type = request.query_params.get('room_type')
        if not support_room.queue:
            needs_routing = True
        elif not support_room.queue.is_active:
            needs_routing = True
        elif requested_type and support_room.queue.room_type != requested_type:
            needs_routing = True

        if needs_routing:
            candidates = SupportRoom.objects.filter(
                is_active=True,
                is_test_room=_is_test_actor(user),
            )
            if requested_type:
                candidates = candidates.filter(room_type=requested_type)
                if not candidates.exists():
                    candidates = SupportRoom.objects.filter(
                        is_active=True,
                        is_test_room=_is_test_actor(user),
                    )
                    if user.user_type == 'player':
                        candidates = candidates.filter(room_type__in=['player', 'all'])
                    elif user.user_type == 'agent':
                        candidates = candidates.filter(room_type__in=['agent', 'all'])
            else:
                if user.user_type == 'player':
                    candidates = candidates.filter(room_type__in=['player', 'all'])
                elif user.user_type == 'agent':
                    candidates = candidates.filter(room_type__in=['agent', 'all'])

            candidates = candidates.annotate(
                load=Count('queued_chats', filter=Q(queued_chats__status='OPEN'))
            ).order_by('load')

            if candidates.exists():
                new_queue = candidates.first()
                if support_room.queue != new_queue:
                    if support_room.queue and support_room.queue.room_type != new_queue.room_type:
                        support_room.current_handler = None
                    support_room.queue = new_queue
                    support_room.is_test_room = new_queue.is_test_room
                    support_room.save()
                    if requested_type and not created:
                        Message.objects.create(
                            room=support_room,
                            sender=user,
                            content=f"System: Connected to {new_queue.name}",
                            is_read=True
                        )

        if support_room.status == 'CLOSED':
            support_room.status = 'OPEN'
            support_room.save()

        support_room.unread_count = support_room.messages.filter(
            is_read=False
        ).exclude(sender=user).count()
        support_room.last_activity = support_room.messages.aggregate(
            max_ts=Max('timestamp')
        )['max_ts'] or support_room.created_at
        support_room.last_message_sender_id = support_room.messages.order_by(
            '-timestamp'
        ).values_list('sender_id', flat=True).first()
        rooms.append(support_room)

        direct_rooms = Room.objects.filter(
            room_type='direct_agent',
            status='OPEN',
            direct_request_status='accepted',
            is_test_room=_is_test_actor(user),
            participants__user=user,
            participants__is_active=True,
        ).distinct().annotate(
            unread_count=Count(
                'messages',
                filter=Q(messages__is_read=False) & ~Q(messages__sender=user)
            ),
            last_activity=Coalesce(Max('messages__timestamp'), 'created_at'),
            last_message_sender_id=Subquery(latest_sender_subquery),
        ).order_by('-unread_count', '-last_activity')
        rooms.extend(list(direct_rooms))

        group_rooms = Room.objects.filter(
            room_type='group',
            status='OPEN',
            is_test_room=_is_test_actor(user),
            participants__user=user,
            participants__is_active=True,
        ).distinct().annotate(
            unread_count=Count(
                'messages',
                filter=Q(messages__is_read=False) & ~Q(messages__sender=user)
            ),
            last_activity=Coalesce(Max('messages__timestamp'), 'created_at'),
            last_message_sender_id=Subquery(latest_sender_subquery),
        ).order_by('-unread_count', '-last_activity')
        rooms.extend(list(group_rooms))
    
    serializer = RoomSerializer(rooms, many=True, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def room_message_requests_view(request):
    """
    List pending direct chat requests for the authenticated non-staff user.
    """
    user = request.user
    if user.user_type == 'staff':
        return Response([], status=status.HTTP_200_OK)

    latest_sender_subquery = Message.objects.filter(
        room=OuterRef('pk')
    ).order_by('-timestamp').values('sender_id')[:1]

    requests_qs = Room.objects.filter(
        room_type='direct_agent',
        status='OPEN',
        direct_request_status='pending',
        is_test_room=_is_test_actor(user),
        participants__user=user,
        participants__is_active=True,
    ).distinct().annotate(
        unread_count=Count(
            'messages',
            filter=Q(messages__is_read=False) & ~Q(messages__sender=user)
        ),
        last_activity=Coalesce(Max('messages__timestamp'), 'created_at'),
        last_message_sender_id=Subquery(latest_sender_subquery),
    ).order_by('-unread_count', '-last_activity')

    serializer = RoomSerializer(requests_qs, many=True, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def room_detail_view(request, room_id):
    """
    Get detailed information about a specific room.
    """
    room = get_object_or_404(Room, id=room_id)
    if not _room_scope_match(room, request.user):
        return Response({'error': 'Not authorized for this room scope'}, status=status.HTTP_403_FORBIDDEN)
    
    # Permission check
    if request.user.user_type != 'staff' and room.client != request.user:
        if not _can_non_staff_access_room(room, request.user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        
    # Staff can only see rooms in their active queue
    if request.user.user_type == 'staff':
        if not _can_staff_access_room(room, request.user):
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
    if not _room_scope_match(room, request.user):
        return Response({'error': 'Not authorized for this room scope'}, status=status.HTTP_403_FORBIDDEN)
    
    # Permission check
    if request.user.user_type != 'staff' and room.client != request.user:
        if not _can_non_staff_access_room(room, request.user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    # Staff can only see rooms in their active queue
    if request.user.user_type == 'staff':
        if not _can_staff_access_room(room, request.user):
            return Response({'error': 'Room not in your queues'}, status=status.HTTP_403_FORBIDDEN)

    # Mark unread messages as read and broadcast read receipts.
    unread_qs = Message.objects.filter(room=room, is_read=False).exclude(sender=request.user)
    read_message_ids = list(unread_qs.values_list('id', flat=True))
    if read_message_ids:
        unread_qs.update(is_read=True)
        channel_layer = get_channel_layer()
        room_group_name = f'chat_{room_id}'
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'chat_message_read',
                'message_ids': read_message_ids,
                'reader_id': request.user.id,
            }
        )

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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def room_message_request_respond_view(request, room_id):
    """
    Accept or reject an incoming direct message request.
    """
    user = request.user
    room = get_object_or_404(
        Room,
        id=room_id,
        room_type='direct_agent',
        status='OPEN',
    )
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this room scope'}, status=status.HTTP_403_FORBIDDEN)
    if user.user_type == 'staff':
        return Response({'error': 'Staff cannot respond to direct message requests.'}, status=status.HTTP_403_FORBIDDEN)
    if not room.participants.filter(user=user, is_active=True).exists():
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    if room.direct_request_status != 'pending':
        return Response({'error': 'This room is not a pending message request.'}, status=status.HTTP_400_BAD_REQUEST)
    if room.direct_request_initiator_id == user.id:
        return Response({'error': 'You cannot respond to your own outgoing request.'}, status=status.HTTP_400_BAD_REQUEST)

    action = (request.data.get('action') or '').strip().lower()
    if action not in ('accept', 'reject'):
        return Response({'error': "action must be 'accept' or 'reject'."}, status=status.HTTP_400_BAD_REQUEST)

    if action == 'accept':
        room.direct_request_status = 'accepted'
        room.direct_request_initiator = None
        room.save(update_fields=['direct_request_status', 'direct_request_initiator'])
    else:
        room.direct_request_status = 'rejected'
        room.status = 'CLOSED'
        room.save(update_fields=['direct_request_status', 'status'])

    serializer = RoomSerializer(room, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pinned_messages_view(request, room_id):
    """
    Get (all) pinned messages for a room.
    """
    room = get_object_or_404(Room, id=room_id)
    if not _room_scope_match(room, request.user):
        return Response({'error': 'Not authorized for this room scope'}, status=status.HTTP_403_FORBIDDEN)
    
    # Permission check (same as room_messages_view)
    if request.user.user_type != 'staff' and room.client != request.user:
        if not _can_non_staff_access_room(room, request.user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    if request.user.user_type == 'staff':
        if not _can_staff_access_room(room, request.user):
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
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this room scope'}, status=status.HTTP_403_FORBIDDEN)
    
    # Permission check
    if user.user_type != 'staff' and room.client != user:
        if not _can_non_staff_access_room(room, user):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        
    # Staff can only upload to rooms in their active queue
    if user.user_type == 'staff':
        if not _can_staff_access_room(room, user):
             return Response({'error': 'Room not in your queues'}, status=status.HTTP_403_FORBIDDEN)

    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

    # Create Message with attachment
    # Content is optional if we have an attachment. We leave it empty if not provided.
    content = request.data.get('content', '')
    reply_to_id_raw = request.data.get('reply_to')
    reply_to_message = None
    if reply_to_id_raw is not None and str(reply_to_id_raw).strip() != '':
        try:
            reply_to_id = int(reply_to_id_raw)
            reply_to_message = Message.objects.filter(id=reply_to_id, room=room).first()
        except (TypeError, ValueError):
            reply_to_message = None
    
    message = Message.objects.create(
        room=room,
        sender=user,
        content=content,
        attachment=file_obj,
        reply_to=reply_to_message,
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
            'user_type': user.user_type,
            'message_id': message.id,
            'timestamp': message.timestamp.isoformat(),
            'is_read': message.is_read,
            'attachment': msg_data['attachment'],
            'is_broadcast': msg_data.get('is_broadcast', False),
            'reply_to': msg_data.get('reply_to'),
            'reply_to_message': msg_data.get('reply_to_message'),
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

    if not _can_user_access_room(message.room, request.user):
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
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this room scope'}, status=status.HTTP_403_FORBIDDEN)
    
    # Permission check
    if user.user_type != 'staff' and room.client != user:
        if not _can_non_staff_access_room(room, user):
            return Response({'error': 'Not authorized to join this room'}, status=status.HTTP_403_FORBIDDEN)
    
    # If staff joins:
    if user.user_type == 'staff':
        if not _can_staff_access_room(room, user):
            return Response({'error': 'Room not in your queues'}, status=status.HTTP_403_FORBIDDEN)
        # If open but no current handler, claim it
        if room.room_type == 'support' and not room.current_handler:
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
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this room scope'}, status=status.HTTP_403_FORBIDDEN)
    
    if user.user_type not in ('staff', 'agent'):
         return Response({'error': 'Only staff or agents can close rooms'}, status=status.HTTP_403_FORBIDDEN)

    if user.user_type == 'agent':
        if room.room_type != 'direct_agent' or room.direct_agent_id != user.id:
            return Response({'error': 'Agents can close only their direct chats'}, status=status.HTTP_403_FORBIDDEN)
    if user.user_type == 'staff' and not _can_staff_access_room(room, user):
        return Response({'error': 'Room not in your queues'}, status=status.HTTP_403_FORBIDDEN)
         
    # Optional: Enforce only current handler can close?
    # if room.current_handler != user:
    #    return Response({'error': 'You are not the current handler'}, status=status.HTTP_403_FORBIDDEN)
        
    room.status = 'CLOSED'
    room.current_handler = None # Clear handler on close logic
    room.resolution_reason = (request.data.get('resolution_reason') or '').strip()[:240]
    room.resolved_at = timezone.now()
    room.resolved_by = user
    room.save(update_fields=['status', 'current_handler', 'resolution_reason', 'resolved_at', 'resolved_by'])
    
    return Response({
        'status': 'closed',
        'message': 'Chat resolved',
        'resolution_reason': room.resolution_reason,
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def quick_replies_view(request):
    user = request.user
    if user.user_type not in ('agent', 'staff'):
        return Response({'error': 'Only staff/agents can manage quick replies'}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        qs = AgentQuickReply.objects.filter(user=user).order_by('title', '-updated_at')
        return Response(
            AgentQuickReplySerializer(qs, many=True, context={'request': request}).data,
            status=status.HTTP_200_OK,
        )

    serializer = AgentQuickReplySerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    reply = AgentQuickReply.objects.create(
        user=user,
        title=serializer.validated_data['title'].strip(),
        content=serializer.validated_data['content'],
    )
    return Response(
        AgentQuickReplySerializer(reply, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def quick_reply_detail_view(request, reply_id):
    user = request.user
    if user.user_type not in ('agent', 'staff'):
        return Response({'error': 'Only staff/agents can manage quick replies'}, status=status.HTTP_403_FORBIDDEN)

    reply = get_object_or_404(AgentQuickReply, id=reply_id, user=user)

    if request.method == 'DELETE':
        reply.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    title = (request.data.get('title') or '').strip()
    content = request.data.get('content')
    if title:
        reply.title = title[:80]
    if content is not None:
        reply.content = content
    reply.save()
    return Response(
        AgentQuickReplySerializer(reply, context={'request': request}).data,
        status=status.HTTP_200_OK,
    )


@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def room_internal_note_view(request, room_id):
    user = request.user
    room = get_object_or_404(Room, id=room_id)
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this room scope'}, status=status.HTTP_403_FORBIDDEN)
    if user.user_type not in ('staff', 'agent'):
        return Response({'error': 'Only staff/agents can access internal notes'}, status=status.HTTP_403_FORBIDDEN)
    if not _can_user_access_room(room, user):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    note, _ = ChatInternalNote.objects.get_or_create(room=room)
    if request.method == 'GET':
        return Response(
            ChatInternalNoteSerializer(note, context={'request': request}).data,
            status=status.HTTP_200_OK,
        )

    content = (request.data.get('content') or '').strip()
    note.content = content
    note.updated_by = user
    note.save(update_fields=['content', 'updated_by', 'updated_at'])
    return Response(
        ChatInternalNoteSerializer(note, context={'request': request}).data,
        status=status.HTTP_200_OK,
    )


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
    active_support_rooms = user.active_support_rooms.filter(is_test_room=_is_test_actor(user))
    room_types = [room.room_type for room in active_support_rooms]

    if not active_support_rooms.exists():
        room_types = []

    base_query = Room.objects.filter(status='OPEN', is_test_room=_is_test_actor(user))
    
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
        room = Room.objects.get(client=user, room_type='support')
    except Room.DoesNotExist:
        return Response({'error': 'No active chat room found'}, status=status.HTTP_404_NOT_FOUND)
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this room scope'}, status=status.HTTP_403_FORBIDDEN)

    current_queue = room.queue
    if not current_queue:
        return Response({'error': 'You are not assigned to a station'}, status=status.HTTP_400_BAD_REQUEST)

    # Find alternative ACTIVE stations of the same type
    # Must be active (staff assigned) and not the current one
    alternatives = SupportRoom.objects.filter(
        room_type=current_queue.room_type,
        is_active=True,
        is_test_room=_is_test_actor(user),
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
    room.is_test_room = new_queue.is_test_room
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agent_search_view(request):
    user = request.user
    if user.user_type != 'player':
        return Response({'error': 'Only players can search agents'}, status=status.HTTP_403_FORBIDDEN)

    query = (request.query_params.get('q') or '').strip()
    qs = User.objects.filter(
        user_type='agent',
        is_active=True,
        is_test_user=_is_test_actor(user),
    )
    if query:
        qs = qs.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )
    qs = qs.annotate(
        availability_rank=Case(
            When(agent_availability='online', then=Value(0)),
            When(agent_availability='busy', then=Value(1)),
            When(agent_availability='away', then=Value(2)),
            When(agent_availability='offline', then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        )
    ).order_by('availability_rank', 'username')[:30]

    data = [
        {
            'id': agent.id,
            'username': agent.username,
            'first_name': agent.first_name,
            'last_name': agent.last_name,
            'is_verified': agent.is_verified,
            'user_type': agent.user_type,
            'agent_availability': agent.agent_availability,
            'agent_status_note': agent.agent_status_note,
            'profile_picture': (
                build_public_absolute_uri(request, agent.profile_picture.url)
                if agent.profile_picture
                else None
            ),
            'profile_thumbnail': (
                build_public_absolute_uri(request, agent.profile_thumbnail.url)
                if getattr(agent, 'profile_thumbnail', None)
                else None
            ),
            'avatar': (
                build_public_absolute_uri(request, agent.profile_thumbnail.url)
                if getattr(agent, 'profile_thumbnail', None)
                else (
                    build_public_absolute_uri(request, agent.profile_picture.url)
                    if agent.profile_picture
                    else None
                )
            ),
        }
        for agent in qs
    ]
    return Response(data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_direct_agent_chat_view(request):
    player = request.user
    if player.user_type != 'player':
        return Response({'error': 'Only players can start direct agent chat'}, status=status.HTTP_403_FORBIDDEN)

    agent_id = request.data.get('agent_id')
    try:
        agent_id = int(agent_id)
    except (TypeError, ValueError):
        return Response({'error': 'agent_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        agent = User.objects.get(
            id=agent_id,
            user_type='agent',
            is_active=True,
            is_test_user=_is_test_actor(player),
        )
    except User.DoesNotExist:
        return Response({'error': 'Agent not found'}, status=status.HTTP_404_NOT_FOUND)

    if agent.agent_availability == 'offline':
        return Response(
            {'error': 'This agent is currently offline. Please choose another agent.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        room, created = _ensure_direct_room_for_users(player, agent)
        _sync_direct_request_state(room, player, agent)

    room.unread_count = room.messages.filter(is_read=False).exclude(sender=player).count()
    payload = RoomSerializer(room, context={'request': request}).data
    payload['created'] = created
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_direct_player_chat_view(request):
    requester = request.user
    if requester.user_type not in ('player', 'agent'):
        return Response({'error': 'Only players and agents can start direct player chat.'}, status=status.HTTP_403_FORBIDDEN)

    target_id = request.data.get('player_id')
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return Response({'error': 'player_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    if target_id == requester.id:
        return Response({'error': 'You cannot start a direct chat with yourself.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        target_player = User.objects.get(
            id=target_id,
            user_type='player',
            is_active=True,
            is_test_user=_is_test_actor(requester),
        )
    except User.DoesNotExist:
        return Response({'error': 'Player not found'}, status=status.HTTP_404_NOT_FOUND)

    left_user = requester
    right_user = target_player
    if target_player.id < requester.id:
        left_user = target_player
        right_user = requester

    with transaction.atomic():
        room, created = _ensure_direct_room_for_users(left_user, right_user)
        _sync_direct_request_state(room, requester, target_player)

    room.unread_count = room.messages.filter(is_read=False).exclude(sender=requester).count()
    payload = RoomSerializer(room, context={'request': request}).data
    payload['created'] = created
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def discover_groups_view(request):
    user = request.user
    query = (request.query_params.get('q') or '').strip()
    qs = Room.objects.filter(
        room_type='group',
        status='OPEN',
        is_test_room=_is_test_actor(user),
    ).select_related('group_admin')
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(group_description__icontains=query))

    requested_map = {
        item['room_id']: item['status']
        for item in GroupJoinRequest.objects.filter(
            player=user,
            room__in=qs,
        ).values('room_id', 'status')
    }
    joined_ids = set(RoomParticipant.objects.filter(
        room__in=qs,
        user=user,
        is_active=True,
    ).values_list('room_id', flat=True))

    data = []
    for room in qs.order_by('-created_at')[:100]:
        relation = 'none'
        if room.id in joined_ids:
            relation = 'member'
        elif room.group_admin_id == user.id:
            relation = 'admin'
        elif requested_map.get(room.id) == 'pending':
            relation = 'pending'
        elif requested_map.get(room.id) == 'rejected':
            relation = 'rejected'
        data.append({
            'id': room.id,
            'name': room.name,
            'group_description': room.group_description,
            'group_admin': room.group_admin.username if room.group_admin else None,
            'member_count': room.participants.filter(is_active=True).exclude(user_id=room.group_admin_id).count(),
            'relation': relation,
        })
    return Response(data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_group_view(request):
    user = request.user
    if user.user_type != 'agent':
        return Response({'error': 'Only agents can create groups'}, status=status.HTTP_403_FORBIDDEN)

    admin_group_count = Room.objects.filter(
        room_type='group',
        status='OPEN',
        group_admin=user,
        is_test_room=_is_test_actor(user),
    ).count()
    if admin_group_count >= 3:
        return Response({'error': 'You can create at most 3 groups'}, status=status.HTTP_400_BAD_REQUEST)

    name = (request.data.get('name') or '').strip()
    description = (request.data.get('group_description') or '').strip()
    if not name:
        return Response({'error': 'Group name is required'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        room = Room.objects.create(
            room_type='group',
            name=name[:100],
            group_description=description[:240],
            group_admin=user,
            status='OPEN',
            is_test_room=_is_test_actor(user),
        )
        RoomParticipant.objects.get_or_create(
            room=room,
            user=user,
            defaults={'is_active': True},
        )

    payload = RoomSerializer(room, context={'request': request}).data
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_group_view(request, room_id):
    user = request.user
    if user.user_type != 'agent':
        return Response({'error': 'Only agents can delete groups'}, status=status.HTTP_403_FORBIDDEN)

    room = get_object_or_404(Room, id=room_id, room_type='group')
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this group scope'}, status=status.HTTP_403_FORBIDDEN)
    if room.group_admin_id != user.id:
        return Response({'error': 'Only the group admin can delete this group'}, status=status.HTTP_403_FORBIDDEN)

    room.delete()
    return Response({'status': 'deleted'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_group_join_view(request, room_id):
    user = request.user
    if user.user_type != 'player':
        return Response({'error': 'Only players can request to join groups'}, status=status.HTTP_403_FORBIDDEN)

    room = get_object_or_404(Room, id=room_id, room_type='group', status='OPEN')
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this group scope'}, status=status.HTTP_403_FORBIDDEN)

    if RoomParticipant.objects.filter(room=room, user=user, is_active=True).exists():
        return Response({'error': 'You are already in this group'}, status=status.HTTP_400_BAD_REQUEST)

    join_request, created = GroupJoinRequest.objects.get_or_create(
        room=room,
        player=user,
        status='pending',
    )
    if not created and join_request.status == 'pending':
        return Response({'error': 'Join request already pending'}, status=status.HTTP_400_BAD_REQUEST)

    if not created and join_request.status in ('approved', 'rejected'):
        join_request.status = 'pending'
        join_request.reviewed_at = None
        join_request.reviewed_by = None
        join_request.save(update_fields=['status', 'reviewed_at', 'reviewed_by'])

    return Response({'status': 'requested'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def managed_group_join_requests_view(request):
    user = request.user
    if user.user_type != 'agent':
        return Response({'error': 'Only agents can view group requests'}, status=status.HTTP_403_FORBIDDEN)

    qs = GroupJoinRequest.objects.filter(
        room__room_type='group',
        room__group_admin=user,
        room__is_test_room=_is_test_actor(user),
        status='pending',
    ).select_related('room', 'player')

    serializer = GroupJoinRequestSerializer(qs, many=True, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def review_group_join_request_view(request, request_id):
    user = request.user
    if user.user_type != 'agent':
        return Response({'error': 'Only agents can review join requests'}, status=status.HTTP_403_FORBIDDEN)

    join_request = get_object_or_404(
        GroupJoinRequest.objects.select_related('room', 'player'),
        id=request_id,
        status='pending',
        room__room_type='group',
        room__group_admin=user,
    )
    if not _room_scope_match(join_request.room, user):
        return Response({'error': 'Not authorized for this group scope'}, status=status.HTTP_403_FORBIDDEN)

    action = (request.data.get('action') or '').strip().lower()
    if action not in ('approve', 'reject'):
        return Response({'error': "action must be 'approve' or 'reject'"}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        join_request.status = 'approved' if action == 'approve' else 'rejected'
        join_request.reviewed_at = timezone.now()
        join_request.reviewed_by = user
        join_request.save(update_fields=['status', 'reviewed_at', 'reviewed_by'])

        if action == 'approve':
            participant, _ = RoomParticipant.objects.get_or_create(
                room=join_request.room,
                user=join_request.player,
                defaults={'is_active': True},
            )
            if not participant.is_active:
                participant.is_active = True
                participant.save(update_fields=['is_active'])

    return Response({'status': join_request.status}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def group_members_view(request, room_id):
    user = request.user
    room = get_object_or_404(Room, id=room_id, room_type='group')
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this group scope'}, status=status.HTTP_403_FORBIDDEN)
    if not _can_non_staff_access_room(room, user):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    participants = RoomParticipant.objects.filter(
        room=room,
        is_active=True,
    ).exclude(
        user_id=room.group_admin_id
    ).select_related('user').order_by('user__username')
    data = [UserSerializer(p.user, context={'request': request}).data for p in participants]
    return Response(data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def group_broadcast_view(request, room_id):
    user = request.user
    room = get_object_or_404(Room, id=room_id, room_type='group', status='OPEN')
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this group scope'}, status=status.HTTP_403_FORBIDDEN)
    if room.group_admin_id != user.id:
        return Response({'error': 'Only the group admin can broadcast'}, status=status.HTTP_403_FORBIDDEN)

    content = (request.data.get('content') or '').strip()
    if not content:
        return Response({'error': 'Broadcast message cannot be empty'}, status=status.HTTP_400_BAD_REQUEST)

    message = Message.objects.create(
        room=room,
        sender=user,
        content=content,
        is_broadcast=True,
    )

    channel_layer = get_channel_layer()
    room_group_name = f'chat_{room.id}'
    async_to_sync(channel_layer.group_send)(
        room_group_name,
        {
            'type': 'chat_message',
            'message': message.content,
            'username': user.username,
            'user_id': user.id,
            'user_type': user.user_type,
            'message_id': message.id,
            'timestamp': message.timestamp.isoformat(),
            'is_read': message.is_read,
            'is_broadcast': True,
        }
    )

    return Response(MessageSerializer(message, context={'request': request}).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_direct_chat_from_group_view(request, room_id, player_id):
    user = request.user
    if user.user_type != 'agent':
        return Response({'error': 'Only agents can start direct chats from groups'}, status=status.HTTP_403_FORBIDDEN)

    group_room = get_object_or_404(Room, id=room_id, room_type='group', status='OPEN')
    if group_room.group_admin_id != user.id:
        return Response({'error': 'Only group admin can start direct chats from this group'}, status=status.HTTP_403_FORBIDDEN)
    if not _room_scope_match(group_room, user):
        return Response({'error': 'Not authorized for this group scope'}, status=status.HTTP_403_FORBIDDEN)

    try:
        player = User.objects.get(
            id=player_id,
            user_type='player',
            is_active=True,
            is_test_user=_is_test_actor(user),
        )
    except User.DoesNotExist:
        return Response({'error': 'Player not found'}, status=status.HTTP_404_NOT_FOUND)

    if not RoomParticipant.objects.filter(room=group_room, user=player, is_active=True).exists():
        return Response({'error': 'Player is not an active member of this group'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        direct_room, created = _ensure_direct_room_for_users(player, user)
        if direct_room.direct_request_status != 'accepted' or direct_room.direct_request_initiator_id is not None:
            direct_room.direct_request_status = 'accepted'
            direct_room.direct_request_initiator = None
            direct_room.save(update_fields=['direct_request_status', 'direct_request_initiator'])

    direct_room.unread_count = direct_room.messages.filter(is_read=False).exclude(sender=user).count()
    payload = RoomSerializer(direct_room, context={'request': request}).data
    payload['created'] = created
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def leave_group_view(request, room_id):
    user = request.user
    if user.user_type != 'player':
        return Response({'error': 'Only players can leave groups'}, status=status.HTTP_403_FORBIDDEN)

    room = get_object_or_404(Room, id=room_id, room_type='group', status='OPEN')
    if not _room_scope_match(room, user):
        return Response({'error': 'Not authorized for this group scope'}, status=status.HTTP_403_FORBIDDEN)
    if room.group_admin_id == user.id:
        return Response({'error': 'Group admin cannot leave the group'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        participant = RoomParticipant.objects.get(room=room, user=user)
    except RoomParticipant.DoesNotExist:
        return Response({'error': 'You are not a member of this group'}, status=status.HTTP_400_BAD_REQUEST)

    participant.is_active = False
    participant.save(update_fields=['is_active'])

    return Response({'status': 'left'}, status=status.HTTP_200_OK)


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
