import hashlib
import uuid

from django.core import signing
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Blog, BlogComment, BlogReaction
from .serializers import BlogSerializer, BlogCommentSerializer


VISITOR_COOKIE_NAME = 'blog_visitor'
VISITOR_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 2  # 2 years


def _client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or ''


def _ensure_visitor(request):
    signed_value = request.COOKIES.get(VISITOR_COOKIE_NAME)
    should_set_cookie = False
    visitor_id = None

    if signed_value:
        try:
            visitor_id = signing.loads(
                signed_value,
                salt='blog-visitor',
                max_age=VISITOR_COOKIE_MAX_AGE,
            )
        except signing.BadSignature:
            visitor_id = None
            should_set_cookie = True

    if not visitor_id:
        visitor_id = str(uuid.uuid4())
        signed_value = signing.dumps(visitor_id, salt='blog-visitor')
        should_set_cookie = True

    return visitor_id, signed_value, should_set_cookie


def _visitor_hash(request):
    visitor_id, signed_value, should_set_cookie = _ensure_visitor(request)
    fingerprint = f'{visitor_id}|{_client_ip(request)}'
    visitor = hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()
    return visitor, signed_value, should_set_cookie


def _set_visitor_cookie(request, response, signed_value, should_set_cookie):
    if should_set_cookie:
        same_site = getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax') or 'Lax'
        secure = bool(getattr(settings, 'SESSION_COOKIE_SECURE', False) or request.is_secure())
        response.set_cookie(
            VISITOR_COOKIE_NAME,
            signed_value,
            max_age=VISITOR_COOKIE_MAX_AGE,
            httponly=True,
            samesite=same_site,
            secure=secure,
        )
    return response


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


@api_view(['GET'])
@permission_classes([AllowAny])
@authentication_classes([])
def blog_interactions_view(request, slug):
    blog = get_object_or_404(Blog, slug=slug, is_published=True)
    visitor_hash, signed_value, should_set_cookie = _visitor_hash(request)

    user_reaction = (
        BlogReaction.objects.filter(blog=blog, visitor_hash=visitor_hash)
        .values_list('reaction_type', flat=True)
        .first()
    )
    likes_count = BlogReaction.objects.filter(
        blog=blog,
        reaction_type=BlogReaction.REACTION_LIKE,
    ).count()
    comments_all_qs = BlogComment.objects.filter(blog=blog, is_hidden=False).order_by('-created_at')
    comments_qs = comments_all_qs[:50]
    has_commented = BlogComment.objects.filter(blog=blog, visitor_hash=visitor_hash).exists()

    data = {
        'likes_count': likes_count,
        'comments_count': comments_all_qs.count(),
        'user_reaction': user_reaction,
        'has_commented': has_commented,
        'comments': BlogCommentSerializer(
            comments_qs,
            many=True,
            context={'visitor_hash': visitor_hash},
        ).data,
    }
    response = Response(data, status=status.HTTP_200_OK)
    return _set_visitor_cookie(request, response, signed_value, should_set_cookie)


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def blog_react_view(request, slug):
    blog = get_object_or_404(Blog, slug=slug, is_published=True)
    visitor_hash, signed_value, should_set_cookie = _visitor_hash(request)

    reaction = request.data.get('reaction')
    existing = BlogReaction.objects.filter(blog=blog, visitor_hash=visitor_hash).first()

    if reaction == BlogReaction.REACTION_LIKE:
        if existing:
            if existing.reaction_type != reaction:
                existing.reaction_type = reaction
                existing.save(update_fields=['reaction_type', 'updated_at'])
        else:
            BlogReaction.objects.create(
                blog=blog,
                visitor_hash=visitor_hash,
                reaction_type=reaction,
            )
    else:
        if existing:
            existing.delete()

    likes_count = BlogReaction.objects.filter(
        blog=blog,
        reaction_type=BlogReaction.REACTION_LIKE,
    ).count()
    data = {
        'likes_count': likes_count,
        'user_reaction': reaction if reaction == BlogReaction.REACTION_LIKE else None,
    }
    response = Response(data, status=status.HTTP_200_OK)
    return _set_visitor_cookie(request, response, signed_value, should_set_cookie)


@api_view(['POST'])
@permission_classes([AllowAny])
@authentication_classes([])
def blog_comment_create_view(request, slug):
    blog = get_object_or_404(Blog, slug=slug, is_published=True)
    visitor_hash, signed_value, should_set_cookie = _visitor_hash(request)

    content = (request.data.get('content') or '').strip()
    display_name = (request.data.get('display_name') or 'Guest').strip()[:80] or 'Guest'
    if not content:
        response = Response(
            {'detail': 'Comment content is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
        return _set_visitor_cookie(request, response, signed_value, should_set_cookie)

    if BlogComment.objects.filter(blog=blog, visitor_hash=visitor_hash).exists():
        response = Response(
            {'detail': 'You have already commented on this post.'},
            status=status.HTTP_409_CONFLICT,
        )
        return _set_visitor_cookie(request, response, signed_value, should_set_cookie)

    comment = BlogComment.objects.create(
        blog=blog,
        visitor_hash=visitor_hash,
        display_name=display_name,
        content=content,
    )
    response = Response(
        BlogCommentSerializer(comment, context={'visitor_hash': visitor_hash}).data,
        status=status.HTTP_201_CREATED,
    )
    return _set_visitor_cookie(request, response, signed_value, should_set_cookie)


@api_view(['DELETE'])
@permission_classes([AllowAny])
@authentication_classes([])
def blog_comment_delete_view(request, comment_id):
    visitor_hash, signed_value, should_set_cookie = _visitor_hash(request)
    comment = get_object_or_404(BlogComment, pk=comment_id)
    if comment.visitor_hash != visitor_hash:
        response = Response(
            {'detail': 'You can only delete your own comments.'},
            status=status.HTTP_403_FORBIDDEN,
        )
        return _set_visitor_cookie(request, response, signed_value, should_set_cookie)

    comment.delete()
    response = Response({'deleted': True}, status=status.HTTP_200_OK)
    return _set_visitor_cookie(request, response, signed_value, should_set_cookie)

