from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model."""
    
    verification_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'user_type', 'is_verified', 'email', 'first_name', 'last_name', 'verification_status']
        read_only_fields = ['id']

    def get_verification_status(self, obj):
        from .models import VerificationRequest
        try:
            latest_request = VerificationRequest.objects.filter(user=obj).latest('created_at')
            return latest_request.status
        except VerificationRequest.DoesNotExist:
            return None


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for user registration."""
    password = serializers.CharField(write_only=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True)
    email = serializers.EmailField(required=True)
    
    class Meta:
        model = User
        fields = ['username', 'password', 'confirm_password', 'user_type', 'email']
    
    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data
    
    def create(self, validated_data):
        validated_data.pop('confirm_password')
        user = User.objects.create_user(**validated_data)
        # User must verify email before they can login
        user.is_active = False
        user.save()
        return user


class VerifyOTPSerializer(serializers.Serializer):
    """Serializer for OTP verification."""
    email = serializers.EmailField(required=True)
    otp_code = serializers.CharField(required=True, min_length=6, max_length=6)
    
    def validate_otp_code(self, value):
        """Ensure OTP code is exactly 6 digits"""
        if not value.isdigit():
            raise serializers.ValidationError("OTP code must contain only digits.")
        return value


class VerifyUserIDSerializer(serializers.Serializer):
    """Serializer for external user ID verification."""
    user_id = serializers.CharField(required=True, max_length=100)
    otp = serializers.CharField(required=True, min_length=6, max_length=6)
    
    def validate_user_id(self, value):
        """Ensure user_id is not empty and trimmed"""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("User ID cannot be empty.")
        return value


class LoginSerializer(serializers.Serializer):
    """Serializer for user login."""
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, data):
        username = data.get('username')
        password = data.get('password')
        
        if username and password:
            user = authenticate(username=username, password=password)
            if not user:
                raise serializers.ValidationError("Invalid username or password.")
            if not user.is_active:
                raise serializers.ValidationError("Please verify your email first. Check your inbox for the OTP code.")
        else:
            raise serializers.ValidationError("Must include username and password.")
        
        data['user'] = user
        return data


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for password change."""
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=6)
    confirm_new_password = serializers.CharField(required=True)
    
    def validate(self, data):
        if data['new_password'] != data['confirm_new_password']:
            raise serializers.ValidationError({"confirm_new_password": "New passwords do not match."})
        return data
