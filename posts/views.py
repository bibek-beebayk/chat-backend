from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Post
from .serializers import PostSerializer

class PostViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows posts to be viewed.
    """
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _filter_by_visibility(self, queryset, user_type):
        # Staff users can see all active posts.
        if user_type == 'staff':
            return queryset

        if user_type == 'agent':
            return queryset.filter(visibility__in=['all', 'agents'])

        # Player users: players + all
        return queryset.filter(visibility__in=['all', 'players'])

    def get_queryset(self):
        user = self.request.user
        user_type = getattr(user, 'user_type', None)

        # Default list endpoint remains pinned-only (used by home pinned section).
        base_queryset = Post.objects.filter(is_active=True, is_pinned=True)
        return self._filter_by_visibility(base_queryset, user_type).order_by('-created_at')

    @action(detail=False, methods=['get'], url_path='feed')
    def feed(self, request):
        user_type = getattr(request.user, 'user_type', None)
        queryset = Post.objects.filter(is_active=True)
        queryset = self._filter_by_visibility(queryset, user_type).order_by('-created_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
