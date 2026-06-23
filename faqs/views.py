from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from .models import FAQ
from .serializers import FAQSerializer


class FAQViewSet(viewsets.ModelViewSet):
    serializer_class = FAQSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _is_staff_user(self):
        return getattr(self.request.user, 'user_type', None) == 'staff'

    def _visible_queryset(self):
        user = self.request.user
        user_type = getattr(user, 'user_type', None)

        audience_filter = Q(audience=FAQ.AUDIENCE_ALL)
        if user_type == 'staff':
            audience_filter |= Q(audience__in=[
                FAQ.AUDIENCE_PLAYERS,
                FAQ.AUDIENCE_AGENTS,
                FAQ.AUDIENCE_STAFF,
            ])
        elif user_type == 'player':
            audience_filter |= Q(audience=FAQ.AUDIENCE_PLAYERS)
        elif user_type == 'agent':
            audience_filter |= Q(audience=FAQ.AUDIENCE_AGENTS)

        return (
            FAQ.objects
            .filter(is_published=True)
            .filter(Q(published_at__isnull=True) | Q(published_at__lte=timezone.now()))
            .filter(audience_filter)
            .order_by('sort_order', '-is_featured', '-published_at', 'question')
        )

    def _staff_queryset(self):
        return FAQ.objects.order_by('sort_order', '-is_featured', '-published_at', 'question')

    def get_queryset(self):
        queryset = self._staff_queryset() if self._is_staff_user() else self._visible_queryset()
        category = self.request.query_params.get('category')
        search = self.request.query_params.get('search')

        if category and category != 'all':
            queryset = queryset.filter(category=category)

        if search:
            queryset = queryset.filter(Q(question__icontains=search) | Q(answer__icontains=search))

        return queryset

    def check_staff_write_permission(self):
        if not self._is_staff_user():
            raise PermissionDenied('Only staff users can manage FAQs.')

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

    @action(detail=False, methods=['get'], url_path='featured')
    def featured(self, request):
        serializer = self.get_serializer(self._visible_queryset().filter(is_featured=True), many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='manage')
    def manage(self, request):
        self.check_staff_write_permission()
        serializer = self.get_serializer(self._staff_queryset(), many=True)
        return Response(serializer.data)
