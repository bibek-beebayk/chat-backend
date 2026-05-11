import json
import re
from django.db.models import Q, Count
from django.db import transaction
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from .models import Post, PostImage, PostLike, PostComment
from .serializers import PostSerializer, PostCommentSerializer
from social.models import UserConnection
from notifications.models import Notification, PushToken
from notifications.fcm import send_push_notification
from chat.models import Room, Message, RoomParticipant


class IsAuthorOrReadOnly(permissions.BasePermission):
    """Only the post author can edit/delete."""
    def has_object_permission(self, request, view, obj):
        if getattr(view, 'action', None) in {'like', 'comments', 'comment_detail', 'share_to_chats'}:
            return bool(request.user and request.user.is_authenticated)
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
    post_share_prefix = 'POST_SHARE::'

    def _send_user_notification(self, *, recipient, actor, title, body, link, ws_type):
        if not recipient or not actor or recipient.id == actor.id:
            return

        Notification.objects.create(
            user=recipient,
            title=title,
            body=body,
            link=link,
        )

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'user_{recipient.id}',
            {
                'type': ws_type,
                'notification_type': ws_type,
                'actor_id': actor.id,
                'actor_username': actor.username,
                'title': title,
                'body': body,
                'link': link,
                'timestamp': timezone.now().isoformat(),
            },
        )

        tokens = list(
            PushToken.objects.filter(user=recipient, is_active=True).values_list(
                'fcm_token', flat=True
            )
        )
        if tokens:
            try:
                send_push_notification(tokens, title, body, link)
            except Exception:
                pass

    def _notify_on_comment_created(self, *, post, comment, actor):
        post_link = f'/posts/{post.id}'
        notified_user_ids = set()

        if comment.parent_id:
            # Notify parent comment author about a reply.
            parent_author = comment.parent.author
            self._send_user_notification(
                recipient=parent_author,
                actor=actor,
                title='New reply to your comment',
                body=f'{actor.username} replied to your comment.',
                link=post_link,
                ws_type='post_reply_notification',
            )
            notified_user_ids.add(parent_author.id)

        # Notify post author about new comment/reply.
        if post.author_id not in notified_user_ids:
            self._send_user_notification(
                recipient=post.author,
                actor=actor,
                title='New comment on your post',
                body=f'{actor.username} commented on your post.',
                link=post_link,
                ws_type='post_comment_notification',
            )

    def _annotated_queryset(self, queryset):
        return queryset.annotate(
            like_count=Count('likes', distinct=True),
            comment_count=Count('comments', filter=Q(comments__is_active=True), distinct=True),
        )

    def _can_user_share_to_room(self, room, user):
        if user.user_type == 'staff':
            if room.room_type in ('direct_agent', 'group'):
                return False
            return (
                room.current_handler_id == user.id
                or (room.queue_id is not None and user.active_support_rooms.filter(id=room.queue_id).exists())
                or room.participants.filter(user=user, is_active=True).exists()
            )

        if room.room_type == 'support':
            return room.client_id == user.id
        if room.room_type in ('direct_agent', 'group'):
            return room.participants.filter(user=user, is_active=True).exists()
        return False

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
        filtered = self._filter_by_visibility(base_queryset, user).order_by('-created_at')
        return self._annotated_queryset(filtered)

    @action(detail=False, methods=['get'], url_path='feed')
    def feed(self, request):
        """All posts feed with visibility filtering."""
        queryset = Post.objects.filter(is_active=True)
        queryset = self._filter_by_visibility(queryset, request.user).order_by('-created_at')
        queryset = self._annotated_queryset(queryset)

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
        queryset = self._annotated_queryset(queryset)

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

    @action(detail=True, methods=['post'], url_path='share-to-chats')
    def share_to_chats(self, request, pk=None):
        post = self.get_object()
        user = request.user

        room_ids_raw = request.data.get('room_ids')
        if not isinstance(room_ids_raw, list):
            raise ValidationError({'room_ids': 'room_ids must be a list of chat room ids.'})

        room_ids = []
        for item in room_ids_raw:
            try:
                room_id = int(item)
            except (TypeError, ValueError):
                continue
            if room_id > 0:
                room_ids.append(room_id)

        room_ids = list(dict.fromkeys(room_ids))
        if not room_ids:
            raise ValidationError({'room_ids': 'Select at least one chat room.'})

        rooms = Room.objects.filter(
            id__in=room_ids,
            status='OPEN',
            is_test_room=bool(getattr(user, 'is_test_user', False)),
        )
        rooms_by_id = {room.id: room for room in rooms}

        accessible_rooms = []
        denied_room_ids = []
        for room_id in room_ids:
            room = rooms_by_id.get(room_id)
            if room is None:
                denied_room_ids.append(room_id)
                continue
            if self._can_user_share_to_room(room, user):
                accessible_rooms.append(room)
            else:
                denied_room_ids.append(room_id)

        if not accessible_rooms:
            return Response(
                {
                    'status': 'error',
                    'code': 'forbidden',
                    'message': 'No selected chats are accessible for sharing.',
                    'errors': {'denied_room_ids': denied_room_ids},
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        title = (post.title or '').strip()
        plain_content = re.sub(r'<[^>]+>', '', post.content or '').strip()
        excerpt = plain_content[:180].strip()
        first_image = post.images.order_by('order', 'id').first()
        image_url = request.build_absolute_uri(first_image.image.url) if first_image else None
        post_url = request.build_absolute_uri(f'/api/posts/{post.id}/')
        payload = {
            'post_id': post.id,
            'title': title,
            'excerpt': excerpt,
            'post_url': post_url,
            'image_url': image_url,
            'author_username': post.author.username if post.author else '',
        }
        message_content = f'{self.post_share_prefix}{json.dumps(payload, separators=(",", ":"))}'

        channel_layer = get_channel_layer()
        created_count = 0
        with transaction.atomic():
            for room in accessible_rooms:
                participant, _ = RoomParticipant.objects.get_or_create(
                    room=room,
                    user=user,
                    defaults={'is_active': True},
                )
                if not participant.is_active:
                    participant.is_active = True
                    participant.save(update_fields=['is_active'])

                message = Message.objects.create(
                    room=room,
                    sender=user,
                    content=message_content,
                )
                created_count += 1

                async_to_sync(channel_layer.group_send)(
                    f'chat_{room.id}',
                    {
                        'type': 'chat_message',
                        'message': message.content,
                        'username': user.username,
                        'user_id': user.id,
                        'user_type': user.user_type,
                        'message_id': message.id,
                        'timestamp': message.timestamp.isoformat(),
                        'is_read': message.is_read,
                        'is_broadcast': message.is_broadcast,
                        'reply_to': None,
                        'reply_to_message': None,
                    }
                )

        return Response(
            {
                'status': 'success',
                'data': {
                    'shared_to_count': created_count,
                    'shared_room_ids': [room.id for room in accessible_rooms],
                    'denied_room_ids': denied_room_ids,
                },
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'], url_path='like')
    def like(self, request, pk=None):
        post = self.get_object()
        existing = PostLike.objects.filter(post=post, user=request.user).first()
        if existing:
            existing.delete()
            liked = False
        else:
            PostLike.objects.create(post=post, user=request.user)
            liked = True

        like_count = PostLike.objects.filter(post=post).count()
        return Response(
            {
                'status': 'success',
                'data': {
                    'liked': liked,
                    'like_count': like_count,
                }
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['get', 'post'], url_path='comments')
    def comments(self, request, pk=None):
        post = self.get_object()

        if request.method.lower() == 'get':
            queryset = PostComment.objects.filter(
                post=post,
                is_active=True,
                parent__isnull=True,
            ).order_by('created_at', 'id')
            serializer = PostCommentSerializer(queryset, many=True, context={'request': request})
            return Response({'status': 'success', 'data': serializer.data}, status=status.HTTP_200_OK)

        content = (request.data.get('content') or '').strip()
        if not content:
            raise ValidationError({'content': 'Comment content is required.'})

        parent = None
        parent_id = request.data.get('parent')
        if parent_id not in [None, '']:
            try:
                parent = PostComment.objects.get(
                    id=int(parent_id),
                    post=post,
                    is_active=True,
                )
            except (PostComment.DoesNotExist, TypeError, ValueError):
                raise ValidationError({'parent': 'Invalid parent comment.'})

        comment = PostComment.objects.create(
            post=post,
            author=request.user,
            parent=parent,
            content=content,
        )
        self._notify_on_comment_created(post=post, comment=comment, actor=request.user)
        serializer = PostCommentSerializer(comment, context={'request': request})
        return Response({'status': 'success', 'data': serializer.data}, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=['patch', 'delete'],
        url_path=r'comments/(?P<comment_id>[^/.]+)',
    )
    def comment_detail(self, request, pk=None, comment_id=None):
        post = self.get_object()
        try:
            comment = PostComment.objects.get(
                id=int(comment_id),
                post=post,
                is_active=True,
            )
        except (PostComment.DoesNotExist, TypeError, ValueError):
            raise ValidationError({'comment': 'Comment not found.'})

        if comment.author_id != request.user.id:
            raise PermissionDenied('You can only edit or delete your own comments.')

        if request.method.lower() == 'patch':
            content = (request.data.get('content') or '').strip()
            if not content:
                raise ValidationError({'content': 'Comment content is required.'})
            comment.content = content
            comment.save(update_fields=['content', 'updated_at'])
            serializer = PostCommentSerializer(comment, context={'request': request})
            return Response({'status': 'success', 'data': serializer.data}, status=status.HTTP_200_OK)

        # Soft-delete comment and all descendants to keep rendered tree consistent.
        pending_ids = [comment.id]
        all_ids = []
        while pending_ids:
            all_ids.extend(pending_ids)
            pending_ids = list(
                PostComment.objects.filter(
                    parent_id__in=pending_ids,
                    is_active=True,
                ).values_list('id', flat=True)
            )

        deleted_count = PostComment.objects.filter(
            id__in=all_ids,
            is_active=True,
        ).update(is_active=False)

        return Response(
            {
                'status': 'success',
                'data': {
                    'deleted_count': deleted_count,
                },
            },
            status=status.HTTP_200_OK,
        )
