from rest_framework import serializers
from .models import Post
from accounts.serializers import UserSerializer
from chat_project.content_utils import normalize_signed_media_urls

class PostSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    content = serializers.SerializerMethodField()

    def get_content(self, obj):
        return normalize_signed_media_urls(obj.content or '')

    class Meta:
        model = Post
        fields = ['id', 'title', 'content', 'image', 'video', 'link', 'visibility', 'is_pinned', 'author', 'created_at']
        read_only_fields = ['id', 'created_at', 'author']
