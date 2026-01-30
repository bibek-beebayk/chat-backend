from rest_framework import serializers
from .models import Event
from django.contrib.auth import get_user_model

User = get_user_model()

class EventSerializer(serializers.ModelSerializer):
    current_prize_pool = serializers.SerializerMethodField()
    participants_count = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ['id', 'title', 'description', 'start_date', 'end_date', 'poster', 'is_active', 'base_prize_pool', 'prize_increment', 'max_prize_pool', 'current_prize_pool', 'participants_count']
        read_only_fields = ['is_active', 'current_prize_pool', 'participants_count']

    def get_participants_count(self, obj):
        return obj.registrations.count()

    def get_current_prize_pool(self, obj):
        return obj.base_prize_pool + (obj.registrations.count() * obj.prize_increment)

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
