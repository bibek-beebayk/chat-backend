from django.db.models import Q
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from .models import Post, PostImage
from .serializers import PostSerializer
from social.models import UserConnection


class IsAuthorOrReadOnly(permissions.BasePermission):
    """Only the post author can edit/delete."""
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.author == request.user


class PostViewSet(viewsets.ModelViewSet):
    """
    API endpoint for creating, viewing, editing, and deleting posts.
    """
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    max_images_per_post = 5

    def _get_connected_user_ids(self, user):
        """Get IDs of users connected (accepted) to the given user."""
        connections = UserConnection.objects.filter(
            Q(requester=user, status='accepted') |
            Q(receiver=user, status='accepted')
        )
        user_ids = set()
        for conn in connections:
            if conn.requester_id == user.id:
                user_ids.add(conn.receiver_id)
            else:
                user_ids.add(conn.requester_id)
        return user_ids

    def _filter_by_visibility(self, queryset, user):
        """Filter posts based on visibility and the requesting user."""
        user_type = getattr(user, 'user_type', None)

        # Staff users can see all active posts
        if user_type == 'staff':
            return queryset

        connected_ids = self._get_connected_user_ids(user)

        # Filter: show posts that are:
        # - public/all (everyone sees)
        # - Legacy: players/agents based on user_type
        # - private: only if author is the current user
        # - connections: only if author is connected to current user OR is the author
        return queryset.filter(
            Q(visibility__in=['public', 'all']) |
            Q(visibility='players', author__user_type='staff') |  # legacy
            Q(visibility='agents', author__user_type='staff') |   # legacy
            Q(visibility='private', author=user) |
            Q(visibility='connections', author=user) |
            Q(visibility='connections', author_id__in=connected_ids)
        ).distinct()

    def get_queryset(self):
        user = self.request.user
        # Keep home list pinned-only, but allow retrieve/update/destroy on all active posts.
        if getattr(self, 'action', None) == 'list':
            base_queryset = Post.objects.filter(is_active=True, is_pinned=True)
        else:
            base_queryset = Post.objects.filter(is_active=True)
        return self._filter_by_visibility(base_queryset, user).order_by('-created_at')

    @action(detail=False, methods=['get'], url_path='feed')
    def feed(self, request):
        """All posts feed with visibility filtering."""
        queryset = Post.objects.filter(is_active=True)
        queryset = self._filter_by_visibility(queryset, request.user).order_by('-created_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='my-posts')
    def my_posts(self, request):
        """List posts created by the authenticated user."""
        queryset = Post.objects.filter(author=request.user, is_active=True).order_by('-created_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def perform_create(self, serializer):
        # Handle uploaded images
        images = self.request.FILES.getlist('images')
        if len(images) > self.max_images_per_post:
            raise ValidationError({
                'images': f'You can upload up to {self.max_images_per_post} images per post.'
            })

        post = serializer.save()
        for idx, image_file in enumerate(images):
            PostImage.objects.create(post=post, image=image_file, order=idx)

    def perform_update(self, serializer):
        post = serializer.save()

        # Handle image updates: keep existing by default, allow selective removal + new uploads.
        images = self.request.FILES.getlist('images')
        remove_ids = set()
        remove_raw = self.request.data.get('remove_image_ids')
        if remove_raw:
            for token in str(remove_raw).split(','):
                token = token.strip()
                if not token:
                    continue
                try:
                    remove_ids.add(int(token))
                except (TypeError, ValueError):
                    continue

        clear_existing = self.request.data.get('clear_images') == 'true'

        existing_count = post.images.count()
        removable_count = post.images.filter(id__in=remove_ids).count() if remove_ids else 0
        base_count_after_removal = 0 if clear_existing else max(existing_count - removable_count, 0)
        final_count = base_count_after_removal + len(images)

        if final_count > self.max_images_per_post:
            raise ValidationError({
                'images': f'You can upload up to {self.max_images_per_post} images per post.'
            })

        if clear_existing:
            post.images.all().delete()
        elif remove_ids:
            post.images.filter(id__in=remove_ids).delete()

        if images:
            current_max_order = post.images.order_by('-order').values_list('order', flat=True).first()
            next_order = (current_max_order + 1) if current_max_order is not None else 0
            for image_file in images:
                PostImage.objects.create(post=post, image=image_file, order=next_order)
                next_order += 1

    def perform_destroy(self, instance):
        # Soft delete
        instance.is_active = False
        instance.save(update_fields=['is_active'])
