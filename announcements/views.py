from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Announcement
from .serializers import AnnouncementSerializer


class AnnouncementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AnnouncementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _visible_queryset(self):
        user = self.request.user
        user_type = getattr(user, 'user_type', None)

        audience_filter = Q(audience=Announcement.AUDIENCE_ALL)
        if user_type == 'staff':
            audience_filter |= Q(audience__in=[
                Announcement.AUDIENCE_PLAYERS,
                Announcement.AUDIENCE_AGENTS,
                Announcement.AUDIENCE_STAFF,
            ])
        elif user_type == 'player':
            audience_filter |= Q(audience=Announcement.AUDIENCE_PLAYERS)
        elif user_type == 'agent':
            audience_filter |= Q(audience=Announcement.AUDIENCE_AGENTS)

        return (
            Announcement.objects
            .filter(is_published=True)
            .filter(Q(published_at__isnull=True) | Q(published_at__lte=timezone.now()))
            .filter(audience_filter)
            .select_related('created_by')
            .order_by('-is_pinned', '-published_at', '-created_at')
        )

    def get_queryset(self):
        return self._visible_queryset()

    @action(detail=False, methods=['get'], url_path='pinned')
    def pinned(self, request):
        queryset = self._visible_queryset().filter(is_pinned=True)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
