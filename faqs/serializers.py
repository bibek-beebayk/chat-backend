from rest_framework import serializers
from .models import FAQ
from chat_project.content_utils import normalize_signed_media_urls


class FAQSerializer(serializers.ModelSerializer):
    answer = serializers.SerializerMethodField()
    category_label = serializers.CharField(source='get_category_display', read_only=True)
    audience_label = serializers.CharField(source='get_audience_display', read_only=True)

    def get_answer(self, obj):
        return normalize_signed_media_urls(obj.answer or '')

    class Meta:
        model = FAQ
        fields = [
            'id',
            'question',
            'answer',
            'category',
            'category_label',
            'audience',
            'audience_label',
            'sort_order',
            'is_featured',
            'published_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
