from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Blog
from .serializers import BlogSerializer


@api_view(['GET'])
@permission_classes([AllowAny])
def blog_feed_view(request):
    """
    Public blog feed endpoint.
    Returns latest published blogs first.
    """
    queryset = Blog.objects.filter(is_published=True).order_by('-published_at', '-created_at')
    serializer = BlogSerializer(queryset, many=True, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def blog_detail_view(request, pk):
    """
    Public blog detail endpoint by id.
    """
    blog = get_object_or_404(Blog, pk=pk, is_published=True)
    serializer = BlogSerializer(blog)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def blog_detail_by_slug_view(request, slug):
    """
    Public blog detail endpoint by slug.
    """
    blog = get_object_or_404(Blog, slug=slug, is_published=True)
    serializer = BlogSerializer(blog)
    return Response(serializer.data, status=status.HTTP_200_OK)

