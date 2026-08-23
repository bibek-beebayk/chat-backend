from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.serializers import UserSerializer
from social.models import UserConnection

from .models import Story, StoryView
from .serializers import StorySerializer


def _connection_ids(user):
    """IDs of everyone `user` has an accepted connection with (either direction)."""
    accepted = UserConnection.objects.filter(
        Q(requester=user) | Q(receiver=user),
        status=UserConnection.STATUS_ACCEPTED,
    ).values_list('requester_id', 'receiver_id')
    ids = set()
    for requester_id, receiver_id in accepted:
        ids.add(requester_id)
        ids.add(receiver_id)
    ids.discard(user.id)
    return ids


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def story_list_view(request):
    """
    GET: story groups (one per author with >=1 active story) visible to the
    requesting user - their own stories plus their accepted connections'.
    Not a public wall.
    POST: create a story authored by the requesting user.
    """
    if request.method == 'POST':
        media = request.FILES.get('media')
        if not media:
            return Response({'media': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        story = Story.objects.create(
            author=request.user,
            media=media,
            caption=(request.data.get('caption') or '').strip()[:280],
        )
        return Response(
            StorySerializer(story, context={'request': request, 'viewed_story_ids': set()}).data,
            status=status.HTTP_201_CREATED,
        )

    visible_author_ids = _connection_ids(request.user) | {request.user.id}
    active_stories = list(
        Story.objects
        .filter(author_id__in=visible_author_ids, expires_at__gt=timezone.now())
        .select_related('author')
        .order_by('author_id', 'created_at')
    )

    stories_by_author = {}
    for story in active_stories:
        stories_by_author.setdefault(story.author_id, []).append(story)

    viewed_story_ids = set(
        StoryView.objects
        .filter(viewer=request.user, story__author_id__in=stories_by_author.keys())
        .values_list('story_id', flat=True)
    )

    # Own stories first, then everyone else (order otherwise arbitrary -
    # dict preserves insertion order from the author_id-sorted queryset).
    ordered_author_ids = sorted(stories_by_author.keys(), key=lambda author_id: author_id != request.user.id)

    context = {'request': request, 'viewed_story_ids': viewed_story_ids}
    results = []
    for author_id in ordered_author_ids:
        stories = stories_by_author[author_id]
        is_own = author_id == request.user.id
        has_unviewed = (not is_own) and any(s.id not in viewed_story_ids for s in stories)
        results.append({
            'author': UserSerializer(stories[0].author, context=context).data,
            'stories': StorySerializer(stories, many=True, context=context).data,
            'has_unviewed': has_unviewed,
            'is_own': is_own,
        })

    return Response(results)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def story_mark_viewed_view(request, story_id):
    story = get_object_or_404(
        Story.objects.filter(expires_at__gt=timezone.now()),
        id=story_id,
    )
    visible_author_ids = _connection_ids(request.user) | {request.user.id}
    if story.author_id not in visible_author_ids:
        return Response({'error': 'Not authorized to view this story.'}, status=status.HTTP_403_FORBIDDEN)

    StoryView.objects.get_or_create(story=story, viewer=request.user)
    return Response({'status': 'viewed'})


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def story_delete_view(request, story_id):
    story = get_object_or_404(Story, id=story_id, author=request.user)
    story.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
