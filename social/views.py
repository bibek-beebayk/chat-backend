from django.contrib.auth import get_user_model
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import Case, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import UserConnection, UserOnboardingState
from .serializers import (
    ConnectionSearchUserSerializer,
    PublicUserProfileSerializer,
    SuggestedUserSerializer,
    UserConnectionSerializer,
    UserOnboardingStateSerializer,
)
from chat.models import Room
from notifications.fcm import send_push_notification
from notifications.models import Notification, PushToken
from django.db.models import Exists, OuterRef

User = get_user_model()


def _is_test_actor(user):
    return bool(getattr(user, 'is_test_user', False))


def _get_or_create_onboarding_state(user):
    state, _ = UserOnboardingState.objects.get_or_create(user=user)
    return state


def _connection_q(user, target):
    return (
        Q(requester=user, receiver=target) |
        Q(requester=target, receiver=user)
    )


def _connection_status(user, target):
    connection = UserConnection.objects.filter(_connection_q(user, target)).order_by('-updated_at').first()
    if not connection:
        return None, 'none'
    if connection.status == UserConnection.STATUS_ACCEPTED:
        return connection, 'connected'
    if connection.status == UserConnection.STATUS_PENDING:
        if connection.requester_id == user.id:
            return connection, 'pending_outgoing'
        return connection, 'pending_incoming'
    if connection.status == UserConnection.STATUS_REJECTED:
        return connection, 'rejected'
    return connection, 'blocked'


def _build_profile_action_state(user, target):
    connection, status_label = _connection_status(user, target)
    can_chat = False
    can_connect = False
    can_disconnect = False
    primary_action = None
    secondary_action = None

    if user.id == target.id:
        return {
            'connection_status': 'self',
            'can_chat': False,
            'can_connect': False,
            'can_disconnect': False,
            'primary_action': None,
            'secondary_action': None,
        }

    if user.user_type == 'player' and target.user_type == 'agent':
        can_chat = True
        can_connect = status_label in ('none', 'rejected')
        can_disconnect = status_label == 'connected'
        primary_action = 'chat'
        if can_disconnect:
            secondary_action = 'disconnect'
        elif can_connect:
            secondary_action = 'connect'
    elif user.user_type == 'player' and target.user_type == 'player':
        can_chat = True
        can_connect = status_label in ('none', 'rejected')
        can_disconnect = status_label == 'connected'
        primary_action = 'chat'
        if can_disconnect:
            secondary_action = 'disconnect'
        elif can_connect:
            secondary_action = 'connect'
    elif user.user_type == 'agent' and target.user_type == 'player':
        can_chat = True
        can_connect = False
        can_disconnect = False
        primary_action = 'chat'

    return {
        'connection': connection,
        'connection_status': status_label,
        'can_chat': can_chat,
        'can_connect': can_connect,
        'can_disconnect': can_disconnect,
        'primary_action': primary_action,
        'secondary_action': secondary_action,
    }


def _excluded_user_ids_for_suggestions(user, target_type):
    ids = {user.id}
    related_connections = UserConnection.objects.filter(
        Q(requester=user) | Q(receiver=user),
    ).exclude(status=UserConnection.STATUS_REJECTED)
    for connection in related_connections:
        other_id = connection.receiver_id if connection.requester_id == user.id else connection.requester_id
        other = None
        if target_type == 'agent':
            other = User.objects.filter(id=other_id, user_type='agent').exists()
        elif target_type == 'player':
            other = User.objects.filter(id=other_id, user_type='player').exists()
        if other:
            ids.add(other_id)
    return ids


def _active_direct_agent_ids_for_player(user):
    if getattr(user, 'user_type', None) != 'player':
        return set()

    return set(
        Room.objects.filter(
            room_type='direct_agent',
            direct_player=user,
            status='OPEN',
            is_test_room=_is_test_actor(user),
        )
        .exclude(direct_agent_id__isnull=True)
        .values_list('direct_agent_id', flat=True)
    )


def _notify_connection_request(requester, receiver, connection):
    title = 'New connection request'
    body = f'{requester.username} sent you a connection request.'
    link = '/connections/pending'

    # Persist in-app notification record.
    Notification.objects.create(
        user=receiver,
        title=title,
        body=body,
        link=link,
    )

    # Real-time in-app websocket notification.
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f'user_{receiver.id}',
        {
            'type': 'connection_request_notification',
            'notification_type': 'connection_request',
            'connection_id': connection.id,
            'requester_id': requester.id,
            'requester_username': requester.username,
            'title': title,
            'body': body,
            'link': link,
            'timestamp': timezone.now().isoformat(),
        },
    )

    # Push notification for offline/background users.
    tokens = list(
        PushToken.objects.filter(user=receiver, is_active=True).values_list(
            'fcm_token',
            flat=True,
        )
    )
    if tokens:
        try:
            send_push_notification(tokens, title, body, link)
        except Exception:
            # Do not break request flow if push delivery fails.
            pass


def _connection_search_queryset(user, target_type, query):
    queryset = User.objects.filter(
        user_type=target_type,
        is_active=True,
        is_test_user=_is_test_actor(user),
    ).exclude(id=user.id)

    if query:
        queryset = queryset.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(agent_status_note__icontains=query)
        )

    return queryset.order_by('username')


def _parse_pagination(request):
    try:
        limit = int(request.query_params.get('limit', 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.query_params.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0

    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    return limit, offset


def _connection_search_payload(user, queryset, target_type, request=None, section='all'):
    accepted_connection_subquery = UserConnection.objects.filter(
        status=UserConnection.STATUS_ACCEPTED,
    ).filter(
        Q(requester=user, receiver=OuterRef('pk')) |
        Q(requester=OuterRef('pk'), receiver=user)
    )
    queryset = queryset.annotate(is_connected=Exists(accepted_connection_subquery))

    if section == 'connected':
        queryset = queryset.filter(is_connected=True).order_by('username')
    elif section == 'not_connected':
        queryset = queryset.filter(is_connected=False).order_by('username')
    else:
        queryset = queryset.order_by('-is_connected', 'username')

    limit, offset = _parse_pagination(request)
    total_count = queryset.count()
    page = list(queryset[offset:offset + limit])

    connected_ids = set()
    connection_status_map = {}

    for target in page:
        _, status_label = _connection_status(user, target)
        connection_status_map[target.id] = status_label
        if status_label == 'connected':
            connected_ids.add(target.id)

    serializer = ConnectionSearchUserSerializer(
        page,
        many=True,
        context={
            'request': request,
            'connected_ids': connected_ids,
            'connection_status_map': connection_status_map,
        },
    )
    data = serializer.data

    return {
        'results': data,
        'meta': {
            'section': section,
            'limit': limit,
            'offset': offset,
            'count': total_count,
            'has_more': (offset + limit) < total_count,
        },
    }


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def onboarding_state_view(request):
    state = _get_or_create_onboarding_state(request.user)

    if request.method == 'GET':
        return Response(UserOnboardingStateSerializer(state).data, status=status.HTTP_200_OK)

    allowed_fields = {
        'has_seen_agent_suggestions',
        'has_seen_player_suggestions',
        'has_completed_social_onboarding',
    }
    updated_fields = []
    for field in allowed_fields:
        if field in request.data:
            setattr(state, field, bool(request.data.get(field)))
            updated_fields.append(field)

    if state.has_completed_social_onboarding and state.completed_at is None:
        state.completed_at = timezone.now()
        updated_fields.append('completed_at')
    elif not state.has_completed_social_onboarding and state.completed_at is not None:
        state.completed_at = None
        updated_fields.append('completed_at')

    if updated_fields:
        state.save(update_fields=updated_fields + ['updated_at'])

    return Response(UserOnboardingStateSerializer(state).data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def suggested_agents_view(request):
    user = request.user
    if user.user_type != 'player':
        return Response([], status=status.HTTP_200_OK)

    excluded_ids = _active_direct_agent_ids_for_player(user)
    queryset = User.objects.filter(
        user_type='agent',
        is_active=True,
        is_test_user=_is_test_actor(user),
    ).exclude(id__in=excluded_ids).annotate(
        availability_rank=Case(
            When(agent_availability='online', then=Value(0)),
            When(agent_availability='busy', then=Value(1)),
            When(agent_availability='away', then=Value(2)),
            When(agent_availability='offline', then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        ),
        verified_rank=Case(
            When(is_verified=True, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
    ).order_by('verified_rank', 'availability_rank', 'username')

    return Response(SuggestedUserSerializer(queryset, many=True, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def suggested_players_view(request):
    user = request.user
    if user.user_type != 'player':
        return Response([], status=status.HTTP_200_OK)

    excluded_ids = _excluded_user_ids_for_suggestions(user, 'player')
    queryset = User.objects.filter(
        user_type='player',
        is_active=True,
        is_test_user=_is_test_actor(user),
    ).exclude(id__in=excluded_ids).annotate(
        verified_rank=Case(
            When(is_verified=True, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
    ).order_by('verified_rank', '-date_joined', 'username')[:5]

    return Response(SuggestedUserSerializer(queryset, many=True, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def public_profile_view(request, user_id):
    target = get_object_or_404(User, id=user_id, is_active=True)
    if _is_test_actor(request.user) != _is_test_actor(target):
        return Response({'error': 'Not authorized for this profile scope'}, status=status.HTTP_403_FORBIDDEN)

    action_state = _build_profile_action_state(request.user, target)
    serializer = PublicUserProfileSerializer(
        target,
        context={
            'request': request,
            **action_state,
        },
    )
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_connection_view(request):
    user = request.user
    if user.user_type != 'player':
        return Response({'error': 'Only players can create social connections right now.'}, status=status.HTTP_403_FORBIDDEN)

    target_id = request.data.get('target_user_id')
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return Response({'error': 'target_user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

    if user.id == target_id:
        return Response({'error': 'You cannot connect with yourself.'}, status=status.HTTP_400_BAD_REQUEST)

    target = get_object_or_404(User, id=target_id, is_active=True)
    if _is_test_actor(user) != _is_test_actor(target):
        return Response({'error': 'Not authorized for this profile scope'}, status=status.HTTP_403_FORBIDDEN)

    if target.user_type not in ('player', 'agent'):
        return Response({'error': 'Connection requests are only available for players or agents.'}, status=status.HTTP_400_BAD_REQUEST)

    existing = UserConnection.objects.filter(_connection_q(user, target)).order_by('-updated_at').first()
    if existing and existing.status in (UserConnection.STATUS_PENDING, UserConnection.STATUS_ACCEPTED, UserConnection.STATUS_BLOCKED):
        return Response(
            {
                'error': 'A connection already exists for this user pair.',
                'connection_status': _connection_status(user, target)[1],
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    initiated_from_onboarding = bool(request.data.get('initiated_from_onboarding', False))
    connection_type = (
        UserConnection.TYPE_PLAYER_AGENT
        if target.user_type == 'agent'
        else UserConnection.TYPE_PLAYER_PLAYER
    )
    new_status = UserConnection.STATUS_PENDING

    if existing and existing.status == UserConnection.STATUS_REJECTED:
        existing.requester = user
        existing.receiver = target
        existing.connection_type = connection_type
        existing.status = new_status
        existing.initiated_from_onboarding = initiated_from_onboarding
        existing.accepted_at = timezone.now() if new_status == UserConnection.STATUS_ACCEPTED else None
        existing.rejected_at = None
        existing.save(
            update_fields=[
                'requester',
                'receiver',
                'connection_type',
                'status',
                'initiated_from_onboarding',
                'accepted_at',
                'rejected_at',
                'updated_at',
            ]
        )
        connection = existing
    else:
        connection = UserConnection.objects.create(
            requester=user,
            receiver=target,
            connection_type=connection_type,
            status=new_status,
            initiated_from_onboarding=initiated_from_onboarding,
        )

    if connection.status == UserConnection.STATUS_PENDING:
        _notify_connection_request(user, target, connection)

    return Response(UserConnectionSerializer(connection, context={'request': request}).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def disconnect_connection_view(request):
    user = request.user
    if user.user_type != 'player':
        return Response({'error': 'Only players can manage social connections right now.'}, status=status.HTTP_403_FORBIDDEN)

    target_id = request.data.get('target_user_id')
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return Response({'error': 'target_user_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

    if user.id == target_id:
        return Response({'error': 'You cannot disconnect from yourself.'}, status=status.HTTP_400_BAD_REQUEST)

    target = get_object_or_404(User, id=target_id, user_type__in=['player', 'agent'], is_active=True)
    if _is_test_actor(user) != _is_test_actor(target):
        return Response({'error': 'Not authorized for this profile scope'}, status=status.HTTP_403_FORBIDDEN)

    expected_connection_type = (
        UserConnection.TYPE_PLAYER_AGENT
        if target.user_type == 'agent'
        else UserConnection.TYPE_PLAYER_PLAYER
    )
    # 1) Active accepted connection (either direction)
    # 2) Outgoing pending request from current user (unsend/cancel request)
    connection = UserConnection.objects.filter(
        _connection_q(user, target),
        connection_type=expected_connection_type,
    ).filter(
        Q(status=UserConnection.STATUS_ACCEPTED) |
        Q(
            status=UserConnection.STATUS_PENDING,
            requester=user,
            receiver=target,
        )
    ).order_by('-updated_at').first()

    if not connection:
        return Response({'error': 'No active or pending outgoing connection found for this user pair.'}, status=status.HTTP_404_NOT_FOUND)

    connection.delete()
    return Response({'status': 'success'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def connection_list_view(request):
    user = request.user
    queryset = UserConnection.objects.filter(
        Q(requester=user) | Q(receiver=user),
    ).order_by('-updated_at', '-created_at')
    return Response(UserConnectionSerializer(queryset, many=True, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def accept_connection_view(request, connection_id):
    user = request.user
    connection = get_object_or_404(UserConnection, id=connection_id, receiver=user, status=UserConnection.STATUS_PENDING)
    connection.status = UserConnection.STATUS_ACCEPTED
    connection.accepted_at = timezone.now()
    connection.rejected_at = None
    connection.save(update_fields=['status', 'accepted_at', 'rejected_at', 'updated_at'])

    Room.objects.filter(
        room_type='direct_agent',
        status='OPEN',
        is_test_room=_is_test_actor(user),
    ).filter(
        Q(direct_player=connection.requester, direct_agent=connection.receiver) |
        Q(direct_player=connection.receiver, direct_agent=connection.requester)
    ).update(
        direct_request_status='accepted',
        direct_request_initiator=None,
    )
    return Response(UserConnectionSerializer(connection, context={'request': request}).data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_connection_view(request, connection_id):
    user = request.user
    connection = get_object_or_404(UserConnection, id=connection_id, receiver=user, status=UserConnection.STATUS_PENDING)
    connection.status = UserConnection.STATUS_REJECTED
    connection.rejected_at = timezone.now()
    connection.accepted_at = None
    connection.save(update_fields=['status', 'accepted_at', 'rejected_at', 'updated_at'])

    Room.objects.filter(
        room_type='direct_agent',
        status='OPEN',
        direct_request_status='pending',
        is_test_room=_is_test_actor(user),
    ).filter(
        Q(direct_player=connection.requester, direct_agent=connection.receiver) |
        Q(direct_player=connection.receiver, direct_agent=connection.requester)
    ).update(
        direct_request_status='rejected',
        status='CLOSED',
    )
    return Response(UserConnectionSerializer(connection, context={'request': request}).data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_agent_connections_view(request):
    user = request.user
    query = (request.query_params.get('q') or '').strip()
    section = (request.query_params.get('section') or 'all').strip().lower()
    if section not in ('all', 'connected', 'not_connected'):
        section = 'all'
    queryset = _connection_search_queryset(user, 'agent', query)
    payload = _connection_search_payload(
        user,
        queryset,
        'agent',
        request=request,
        section=section,
    )
    return Response(payload, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_player_connections_view(request):
    user = request.user
    query = (request.query_params.get('q') or '').strip()
    section = (request.query_params.get('section') or 'all').strip().lower()
    if section not in ('all', 'connected', 'not_connected'):
        section = 'all'
    queryset = _connection_search_queryset(user, 'player', query)
    payload = _connection_search_payload(
        user,
        queryset,
        'player',
        request=request,
        section=section,
    )
    return Response(payload, status=status.HTTP_200_OK)
