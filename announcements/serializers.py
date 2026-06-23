from rest_framework import serializers
from .models import Announcement
from accounts.serializers import UserSerializer
from chat_project.content_utils import normalize_signed_media_urls


class AnnouncementSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    content = serializers.CharField(required=False, allow_blank=True)
    cover_image = serializers.ImageField(required=False, allow_null=True)
    category_label = serializers.CharField(source='get_category_display', read_only=True)
    audience_label = serializers.CharField(source='get_audience_display', read_only=True)
    priority_label = serializers.CharField(source='get_priority_display', read_only=True)

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
            'is_published',
            'published_at',
            'created_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'category_label',
            'audience_label',
            'priority_label',
            'created_by',
            'created_at',
            'updated_at',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['content'] = normalize_signed_media_urls(instance.content or '')
        return data
