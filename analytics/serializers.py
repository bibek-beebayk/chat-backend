from rest_framework import serializers

from .models import AnalyticsEvent


class AnalyticsTrackSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=AnalyticsEvent.EVENT_CHOICES)
    event_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    path = serializers.CharField(required=False, allow_blank=True, max_length=255)
    full_path = serializers.CharField(required=False, allow_blank=True, max_length=500)
    referrer = serializers.CharField(required=False, allow_blank=True, max_length=500)
    anonymous_id = serializers.CharField(required=False, allow_blank=True, max_length=80)
    session_id = serializers.CharField(required=False, allow_blank=True, max_length=80)
    source = serializers.CharField(required=False, allow_blank=True, max_length=120)
    medium = serializers.CharField(required=False, allow_blank=True, max_length=120)
    campaign = serializers.CharField(required=False, allow_blank=True, max_length=160)
    metadata = serializers.JSONField(required=False)

    def validate_metadata(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Metadata must be an object.')
        return value
