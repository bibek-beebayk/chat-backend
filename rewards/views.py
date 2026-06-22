from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .models import LoginStreak, StreakRedemptionRequest, STREAK_REWARD_AMOUNT
from .serializers import (
    LoginStreakStatusSerializer,
    RedemptionCreateSerializer,
    RedemptionStatusUpdateSerializer,
    StreakRedemptionRequestSerializer,
)
from .services import (
    clear_streak_after_redemption,
    expire_stale_streak,
    record_daily_visit,
)


def _is_staff_user(user):
    return bool(user and user.is_authenticated and getattr(user, 'user_type', None) == 'staff')


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def streak_status_view(request):
    streak = expire_stale_streak(request.user)
    return Response(LoginStreakStatusSerializer(streak).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def record_streak_visit_view(request):
    streak = record_daily_visit(request.user)
    if not streak:
        return Response({'error': 'Only players can build visit streaks.'}, status=status.HTTP_403_FORBIDDEN)
    return Response(LoginStreakStatusSerializer(streak).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_redemption_request_view(request):
    if getattr(request.user, 'user_type', None) != 'player':
        return Response({'error': 'Only players can request streak redemptions.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = RedemptionCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    with transaction.atomic():
        streak = expire_stale_streak(request.user)
        if streak.receivable_bonus < STREAK_REWARD_AMOUNT:
            return Response({'error': 'No streak bonus is currently available to redeem.'}, status=status.HTTP_400_BAD_REQUEST)

        active_request = (
            StreakRedemptionRequest.objects
            .select_for_update()
            .filter(user=request.user, status__in=StreakRedemptionRequest.ACTIVE_STATUSES)
            .first()
        )
        if active_request:
            return Response(
                {'error': 'You already have a redeem request in progress.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        redeem_request = StreakRedemptionRequest.objects.create(
            user=request.user,
            amount=streak.receivable_bonus,
            hi_rollin_username=serializer.validated_data['hi_rollin_username'],
            note=serializer.validated_data.get('note', ''),
        )

    return Response(StreakRedemptionRequestSerializer(redeem_request).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def redemption_request_list_view(request):
    if not _is_staff_user(request.user):
        return Response({'error': 'Only staff can view redemption requests.'}, status=status.HTTP_403_FORBIDDEN)

    queryset = StreakRedemptionRequest.objects.select_related('user', 'reviewed_by').all()
    status_filter = request.query_params.get('status')
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    return Response(StreakRedemptionRequestSerializer(queryset, many=True).data)


@api_view(['PATCH'])
@permission_classes([permissions.IsAuthenticated])
def redemption_request_update_view(request, request_id):
    if not _is_staff_user(request.user):
        return Response({'error': 'Only staff can update redemption requests.'}, status=status.HTTP_403_FORBIDDEN)

    serializer = RedemptionStatusUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    new_status = serializer.validated_data['status']
    staff_note = serializer.validated_data.get('staff_note', '')

    with transaction.atomic():
        redeem_request = (
            StreakRedemptionRequest.objects
            .select_for_update()
            .select_related('user')
        )
        redeem_request = get_object_or_404(redeem_request, pk=request_id)

        if redeem_request.status == StreakRedemptionRequest.STATUS_COMPLETED:
            return Response({'error': 'This request is already completed.'}, status=status.HTTP_400_BAD_REQUEST)
        if redeem_request.status == StreakRedemptionRequest.STATUS_REJECTED:
            return Response({'error': 'This request is already rejected.'}, status=status.HTTP_400_BAD_REQUEST)
        if redeem_request.status == StreakRedemptionRequest.STATUS_PENDING and new_status == StreakRedemptionRequest.STATUS_COMPLETED:
            return Response({'error': 'Approve this request before completing it.'}, status=status.HTTP_400_BAD_REQUEST)
        if redeem_request.status == StreakRedemptionRequest.STATUS_APPROVED and new_status != StreakRedemptionRequest.STATUS_COMPLETED:
            return Response({'error': 'Approved requests can only be completed.'}, status=status.HTTP_400_BAD_REQUEST)
        if new_status == StreakRedemptionRequest.STATUS_COMPLETED and redeem_request.status != StreakRedemptionRequest.STATUS_APPROVED:
            return Response({'error': 'This request cannot be completed.'}, status=status.HTTP_400_BAD_REQUEST)
        if new_status == StreakRedemptionRequest.STATUS_COMPLETED:
            streak = expire_stale_streak(redeem_request.user)
            if streak.receivable_bonus < redeem_request.amount:
                return Response(
                    {'error': 'This player no longer has an active 7-day streak bonus.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        redeem_request.mark_reviewed(request.user, new_status, staff_note)
        redeem_request.save(update_fields=['status', 'staff_note', 'reviewed_by', 'reviewed_at', 'completed_at', 'updated_at'])

        if new_status == StreakRedemptionRequest.STATUS_COMPLETED:
            clear_streak_after_redemption(redeem_request.user)

    return Response(StreakRedemptionRequestSerializer(redeem_request).data)
