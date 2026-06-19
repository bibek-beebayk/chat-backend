from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from events.models import Event
from rewards.models import LoginStreak
from .models import ActivityEvent


User = get_user_model()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def home_stats_view(request):
    now = timezone.now()
    online_cutoff = now - timedelta(minutes=15)

    active_members = User.objects.filter(is_active=True).count()
    online_now = User.objects.filter(is_active=True, last_login__gte=online_cutoff).count()
    active_events = Event.objects.filter(start_date__lte=now, end_date__gte=now).count()
    redeemable_bonuses = LoginStreak.objects.filter(receivable_bonus__gt=0).count()

    return Response({
        'active_members': active_members,
        'online_now': online_now,
        'redeemable_bonuses': redeemable_bonuses,
        'active_events': active_events,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def recent_activity_view(request):
    limit = parse_limit(request.query_params.get('limit'), default=6, maximum=20)
    activities = ActivityEvent.objects.select_related('actor').order_by('-created_at')[:limit]

    return Response([
        {
            'id': activity.id,
            'kind': activity.kind,
            'actor': {
                'id': activity.actor_id,
                'username': activity.actor.username if activity.actor else 'Community',
                'avatar': build_actor_avatar_url(request, activity.actor),
            } if activity.actor else None,
            'action': activity.action,
            'target_title': activity.target_title,
            'target_url': activity.target_url,
            'created_at': activity.created_at,
        }
        for activity in activities
    ])


def build_actor_avatar_url(request, actor):
    if not actor:
        return None

    avatar = (
        getattr(actor, 'profile_thumbnail', None)
        or getattr(actor, 'avatar', None)
        or getattr(actor, 'profile_picture', None)
    )
    if not avatar:
        return None

    try:
        url = avatar.url
    except ValueError:
        return None

    return request.build_absolute_uri(url)


def parse_limit(value, default=6, maximum=20):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, maximum))
