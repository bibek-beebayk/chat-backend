from rest_framework import viewsets, permissions
from .models import Post
from .serializers import PostSerializer

class PostViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows posts to be viewed.
    """
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        user_type = getattr(user, 'user_type', None)

        base_queryset = Post.objects.filter(is_active=True)

        # Staff users can see all active posts.
        if user_type == 'staff':
            return base_queryset.order_by('-created_at')

        if user_type == 'agent':
            return base_queryset.filter(visibility__in=['all', 'agents']).order_by('-created_at')

        # Player users: players + all
        return base_queryset.filter(visibility__in=['all', 'players']).order_by('-created_at')
