from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from events.models import Event
from rewards.models import LoginStreak
from .models import ActivityEvent, AnalyticsEvent
from .serializers import AnalyticsTrackSerializer
from .services import track_event


User = get_user_model()


def is_staff_user(user):
    return bool(user and user.is_authenticated and getattr(user, 'user_type', None) == 'staff')


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


@api_view(['POST'])
@permission_classes([AllowAny])
def track_view(request):
    serializer = AnalyticsTrackSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    metadata = data.get('metadata') or {}
    if (
        data['event_type'] == AnalyticsEvent.EVENT_PAGE_VIEW
        and metadata.get('user_type') == 'staff'
    ):
        return Response({'tracked': False, 'reason': 'staff_page_view_ignored'}, status=status.HTTP_200_OK)

    track_event(
        request=request,
        event_type=data['event_type'],
        event_name=data.get('event_name', ''),
        path=data.get('path', ''),
        full_path=data.get('full_path', ''),
        referrer=data.get('referrer', ''),
        anonymous_id=data.get('anonymous_id', ''),
        session_id=data.get('session_id', ''),
        source=data.get('source', ''),
        medium=data.get('medium', ''),
        campaign=data.get('campaign', ''),
        metadata=metadata,
    )
    return Response({'tracked': True}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_view(request):
    if not is_staff_user(request.user):
        return Response({'error': 'Only staff users can view analytics.'}, status=status.HTTP_403_FORBIDDEN)

    start, end = parse_date_range(request)
    queryset = AnalyticsEvent.objects.filter(created_at__gte=start, created_at__lt=end)
    user_type = request.query_params.get('user_type', '').strip()
    event_type = request.query_params.get('event_type', '').strip()
    if user_type:
        queryset = queryset.filter(user_type=user_type)
    if event_type:
        queryset = queryset.filter(event_type=event_type)

    previous_start = start - (end - start)
    previous_queryset = AnalyticsEvent.objects.filter(created_at__gte=previous_start, created_at__lt=start)
    if user_type:
        previous_queryset = previous_queryset.filter(user_type=user_type)
    if event_type:
        previous_queryset = previous_queryset.filter(event_type=event_type)

    visits = queryset.filter(event_type=AnalyticsEvent.EVENT_PAGE_VIEW).count()
    previous_visits = previous_queryset.filter(event_type=AnalyticsEvent.EVENT_PAGE_VIEW).count()
    unique_visitors = count_unique_visitors(queryset)
    registrations = queryset.filter(event_type=AnalyticsEvent.EVENT_REGISTER).count()
    logins = queryset.filter(event_type=AnalyticsEvent.EVENT_LOGIN).count()

    return Response({
        'range': {
            'start': start,
            'end': end,
            'days': (end - start).days,
        },
        'kpis': {
            'visits': visits,
            'unique_visitors': unique_visitors,
            'registrations': registrations,
            'logins': logins,
            'registration_rate': round((registrations / unique_visitors) * 100, 2) if unique_visitors else 0,
            'visit_change_percent': percent_change(previous_visits, visits),
        },
        'trends': trend_rows(queryset, start, end),
        'user_types': bucket_counts(queryset.exclude(user_type=''), 'user_type'),
        'event_types': bucket_counts(queryset, 'event_type'),
        'top_pages': bucket_counts(
            queryset.filter(event_type=AnalyticsEvent.EVENT_PAGE_VIEW).exclude(path=''),
            'path',
            limit=10,
        ),
        'traffic_sources': bucket_counts(queryset.exclude(source=''), 'source', limit=10),
        'devices': bucket_counts(queryset.exclude(device_type=''), 'device_type'),
        'browsers': bucket_counts(queryset.exclude(browser=''), 'browser'),
        'locations': bucket_counts(queryset.exclude(country=''), 'country', limit=10),
        'recent_events': [
            serialize_analytics_event(event)
            for event in queryset.select_related('user').order_by('-created_at')[:30]
        ],
    })


def parse_date_range(request):
    days = parse_limit(request.query_params.get('days'), default=30, maximum=365)
    end = timezone.now()
    start = end - timedelta(days=days)
    return start, end


def count_unique_visitors(queryset):
    authenticated = queryset.exclude(user_id__isnull=True).values('user_id').distinct().count()
    anonymous = queryset.filter(user_id__isnull=True).exclude(anonymous_id='').values('anonymous_id').distinct().count()
    anonymous_without_id = queryset.filter(user_id__isnull=True, anonymous_id='').exclude(ip_hash='').values('ip_hash').distinct().count()
    return authenticated + anonymous + anonymous_without_id


def percent_change(previous, current):
    if previous == 0:
        return 100 if current > 0 else 0
    return round(((current - previous) / previous) * 100, 2)


def trend_rows(queryset, start, end):
    rows = (
        queryset
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(
            visits=Count('id', filter=Q(event_type=AnalyticsEvent.EVENT_PAGE_VIEW)),
            registrations=Count('id', filter=Q(event_type=AnalyticsEvent.EVENT_REGISTER)),
            logins=Count('id', filter=Q(event_type=AnalyticsEvent.EVENT_LOGIN)),
        )
        .order_by('day')
    )
    by_day = {row['day']: row for row in rows}
    data = []
    cursor = start.date()
    while cursor < end.date() + timedelta(days=1):
        row = by_day.get(cursor, {})
        data.append({
            'date': cursor.isoformat(),
            'visits': row.get('visits', 0),
            'registrations': row.get('registrations', 0),
            'logins': row.get('logins', 0),
        })
        cursor += timedelta(days=1)
    return data


def bucket_counts(queryset, field, limit=8):
    return [
        {
            'label': row[field] or 'Unknown',
            'count': row['count'],
        }
        for row in queryset.values(field).annotate(count=Count('id')).order_by('-count', field)[:limit]
    ]


def serialize_analytics_event(event):
    return {
        'id': event.id,
        'event_type': event.event_type,
        'event_name': event.event_name,
        'user': {
            'id': event.user_id,
            'username': event.user.username,
            'user_type': event.user.user_type,
        } if event.user else None,
        'user_type': event.user_type,
        'path': event.path,
        'source': event.source,
        'device_type': event.device_type,
        'browser': event.browser,
        'country': event.country,
        'metadata': event.metadata,
        'created_at': event.created_at,
    }
