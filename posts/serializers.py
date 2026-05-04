from rest_framework import serializers
from .models import Post, PostImage, PostComment
from accounts.serializers import UserSerializer
from chat_project.content_utils import normalize_signed_media_urls


class PostImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostImage
        fields = ['id', 'image', 'order']
        read_only_fields = ['id']


class PostSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    content = serializers.SerializerMethodField()
    images = PostImageSerializer(many=True, read_only=True)
    like_count = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    # Write-only field for the raw content (bypasses get_content)
    raw_content = serializers.CharField(write_only=True, required=False, source='content')

    def get_content(self, obj):
        return normalize_signed_media_urls(obj.content or '')

    def get_like_count(self, obj):
        annotated = getattr(obj, 'like_count', None)
        if annotated is not None:
            return int(annotated)
        return obj.likes.count()

    def get_comment_count(self, obj):
        annotated = getattr(obj, 'comment_count', None)
        if annotated is not None:
            return int(annotated)
        return obj.comments.filter(is_active=True).count()

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        return obj.likes.filter(user=request.user).exists()

    class Meta:
        model = Post
        fields = [
            'id', 'title', 'content', 'raw_content', 'image', 'video',
            'link', 'visibility', 'is_pinned', 'author', 'images',
            'like_count', 'comment_count', 'is_liked',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'author', 'is_pinned']

    def create(self, validated_data):
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Only the author can update
        request = self.context.get('request')
        if request and instance.author != request.user:
            raise serializers.ValidationError('You can only edit your own posts.')
        return super().update(instance, validated_data)


class PostCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = PostComment
        fields = [
            'id', 'post', 'author', 'parent', 'content',
            'replies', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'post', 'author', 'replies', 'created_at', 'updated_at']

    def get_replies(self, obj):
        qs = obj.replies.filter(is_active=True).order_by('created_at', 'id')
        serializer = PostCommentSerializer(
            qs,
            many=True,
            context=self.context,
        )
        return serializer.data
