from rest_framework import serializers
from .models import Post, PostImage
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
    # Write-only field for the raw content (bypasses get_content)
    raw_content = serializers.CharField(write_only=True, required=False, source='content')

    def get_content(self, obj):
        return normalize_signed_media_urls(obj.content or '')

    class Meta:
        model = Post
        fields = [
            'id', 'title', 'content', 'raw_content', 'image', 'video',
            'link', 'visibility', 'is_pinned', 'author', 'images',
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
