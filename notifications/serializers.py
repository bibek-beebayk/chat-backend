from rest_framework import serializers
from .models import Notification, PushToken

class PushTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushToken
        fields = ['fcm_token', 'device', 'browser']


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'body', 'link', 'is_read', 'created_at']
        read_only_fields = fields
