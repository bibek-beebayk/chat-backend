from rest_framework import serializers
from .models import FAQ
from chat_project.content_utils import normalize_signed_media_urls


class FAQSerializer(serializers.ModelSerializer):
    answer = serializers.CharField(required=False, allow_blank=True)
    category_label = serializers.CharField(source='get_category_display', read_only=True)
    audience_label = serializers.CharField(source='get_audience_display', read_only=True)

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
            'created_by',
            'created_at',
            'updated_at',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['answer'] = normalize_signed_media_urls(instance.answer or '')
        return data
