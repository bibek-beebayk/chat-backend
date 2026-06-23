from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from .models import Announcement
from .serializers import AnnouncementSerializer


class AnnouncementViewSet(viewsets.ModelViewSet):
    serializer_class = AnnouncementSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _is_staff_user(self):
        return getattr(self.request.user, 'user_type', None) == 'staff'

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

    def _staff_queryset(self):
        return (
            Announcement.objects
            .select_related('created_by')
            .order_by('-is_pinned', '-published_at', '-created_at')
        )

    def get_queryset(self):
        if self._is_staff_user():
            return self._staff_queryset()
        return self._visible_queryset()

    def check_staff_write_permission(self):
        if not self._is_staff_user():
            raise PermissionDenied('Only staff users can manage announcements.')

    def create(self, request, *args, **kwargs):
        self.check_staff_write_permission()
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        self.check_staff_write_permission()
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self.check_staff_write_permission()
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self.check_staff_write_permission()
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'], url_path='pinned')
    def pinned(self, request):
        queryset = self._visible_queryset().filter(is_pinned=True)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='manage')
    def manage(self, request):
        self.check_staff_write_permission()
        serializer = self.get_serializer(self._staff_queryset(), many=True)
        return Response(serializer.data)
