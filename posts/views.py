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

        # Staff/admin users: staff + all
        if user_type == 'staff':
            return base_queryset.filter(visibility__in=['all', 'staff']).order_by('-created_at')

        # Player/agent users: player + all
        return base_queryset.filter(visibility__in=['all', 'player']).order_by('-created_at')
