from rest_framework import serializers
from .models import Event
from django.contrib.auth import get_user_model

User = get_user_model()

class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ['id', 'title', 'description', 'start_date', 'end_date', 'poster', 'is_active']

class RegisterInitSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    event_id = serializers.IntegerField(required=False) # Optional, strictly speaking, but good for tracking

class VerifyEventOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp_code = serializers.CharField(required=True, min_length=6, max_length=6)
    event_id = serializers.IntegerField(required=False)

class SetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    password = serializers.CharField(required=True, min_length=6)
    confirm_password = serializers.CharField(required=True, min_length=6)

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return data
