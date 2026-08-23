from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .models import PointAction, PointsBalance, PointsLedgerEntry, PointsRedemptionConfig, PointsRedemptionRequest
from .serializers import (
    AwardPointsSerializer,
    PointActionSerializer,
    PointsBalanceSerializer,
    PointsLedgerEntrySerializer,
    PointsRedemptionRequestSerializer,
    RedemptionCreateSerializer,
    RedemptionStatusUpdateSerializer,
)
from .services import (
    ActiveRedemptionExists,
    BelowMinimumRedemption,
    DailyCapExceeded,
    InsufficientPoints,
    award_points,
    create_redemption_request,
    review_redemption_request,
)


def _is_staff_user(user):
    return bool(user and user.is_authenticated and getattr(user, 'user_type', None) == 'staff')


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def balance_view(request):
    balance, _ = PointsBalance.objects.get_or_create(user=request.user)
    return Response(PointsBalanceSerializer(balance).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def ledger_view(request):
    # limit/offset paging, following the same {results, meta} convention as
    # social/views.py's _parse_pagination-backed search endpoints.
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

    queryset = (
        PointsLedgerEntry.objects
        .filter(user=request.user)
        .select_related('action')
        .order_by('-created_at')
    )
    total_count = queryset.count()
    page = queryset[offset:offset + limit]

    return Response({
        'results': PointsLedgerEntrySerializer(page, many=True).data,
        'meta': {
            'limit': limit,
            'offset': offset,
            'count': total_count,
            'has_more': (offset + limit) < total_count,
        },
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_redemption_view(request):
    if getattr(request.user, 'user_type', None) != 'player':
        return Response({'error': 'Only players can request points redemptions.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = RedemptionCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        redemption_request = create_redemption_request(
            request.user,
            serializer.validated_data['points_amount'],
            note=serializer.validated_data.get('note', ''),
            reward_description=serializer.validated_data.get('reward_description', ''),
        )
    except BelowMinimumRedemption as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except InsufficientPoints:
        return Response({'error': 'You do not have enough points for this redemption.'}, status=status.HTTP_400_BAD_REQUEST)
    except ActiveRedemptionExists:
        return Response({'error': 'You already have a redemption request in progress.'}, status=status.HTTP_400_BAD_REQUEST)

    return Response(PointsRedemptionRequestSerializer(redemption_request).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def redemption_list_view(request):
    if not _is_staff_user(request.user):
        return Response({'error': 'Only staff can view points redemption requests.'}, status=status.HTTP_403_FORBIDDEN)

    queryset = PointsRedemptionRequest.objects.select_related('user', 'reviewed_by').all()
    status_filter = request.query_params.get('status')
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    return Response(PointsRedemptionRequestSerializer(queryset, many=True).data)


@api_view(['PATCH'])
@permission_classes([permissions.IsAuthenticated])
def redemption_update_view(request, request_id):
    if not _is_staff_user(request.user):
        return Response({'error': 'Only staff can update points redemption requests.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = RedemptionStatusUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    redemption_request = get_object_or_404(PointsRedemptionRequest, pk=request_id)

    try:
        redemption_request = review_redemption_request(
            redemption_request,
            request.user,
            serializer.validated_data['status'],
            staff_note=serializer.validated_data.get('staff_note', ''),
        )
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(PointsRedemptionRequestSerializer(redemption_request).data)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def info_view(request):
    """
    Player-facing explainer for the Reward Points top-bar badge: how to
    earn them, and the current (staff-configurable) redemption minimum and
    conversion rate. Deliberately separate from the staff-only
    action_list_view - only actions marked is_visible_to_players are
    included, so internal/one-off bookkeeping actions never leak here.
    """
    config = PointsRedemptionConfig.get_solo()
    actions = PointAction.objects.filter(is_active=True, is_visible_to_players=True).order_by('slug')
    return Response({
        'min_redemption_points': config.min_redemption_points,
        'rp_to_credit_rate': str(config.rp_to_credit_rate),
        'earn_actions': [
            {
                'slug': action.slug,
                'label': action.label,
                'points_value': action.points_value,
                'description': action.description,
            }
            for action in actions
        ],
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def action_list_view(request):
    if not _is_staff_user(request.user):
        return Response({'error': 'Only staff can view point actions.'}, status=status.HTTP_403_FORBIDDEN)

    actions = PointAction.objects.all()
    return Response(PointActionSerializer(actions, many=True).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def award_points_view(request):
    if not _is_staff_user(request.user):
        return Response({'error': 'Only staff can award points.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = AwardPointsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    target_user = get_object_or_404(get_user_model(), pk=serializer.validated_data['user_id'])

    try:
        entry = award_points(
            target_user,
            serializer.validated_data['action_slug'],
            idempotency_key=serializer.validated_data.get('idempotency_key', ''),
            note=serializer.validated_data.get('note', ''),
            awarded_by=request.user,
        )
    except PointAction.DoesNotExist:
        return Response({'error': 'Unknown or inactive point action.'}, status=status.HTTP_400_BAD_REQUEST)
    except DailyCapExceeded as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(PointsLedgerEntrySerializer(entry).data, status=status.HTTP_201_CREATED)
