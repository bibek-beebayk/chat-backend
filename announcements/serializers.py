from rest_framework import serializers
from .models import Announcement
from accounts.serializers import UserSerializer
from chat_project.content_utils import normalize_signed_media_urls


class AnnouncementSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    content = serializers.SerializerMethodField()
    category_label = serializers.CharField(source='get_category_display', read_only=True)
    audience_label = serializers.CharField(source='get_audience_display', read_only=True)
    priority_label = serializers.CharField(source='get_priority_display', read_only=True)

    def get_content(self, obj):
        return normalize_signed_media_urls(obj.content or '')

    class Meta:
        model = Announcement
        fields = [
            'id',
            'title',
            'summary',
            'content',
            'cover_image',
            'category',
            'category_label',
            'audience',
            'audience_label',
            'priority',
            'priority_label',
            'is_pinned',
            'published_at',
            'created_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
