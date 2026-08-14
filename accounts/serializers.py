from rest_framework import serializers
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.contrib.auth import get_user_model
from .models import HomeInfoSection, HomeInfoPoint
from chat_project.url_utils import build_public_absolute_uri
from rewards.services import record_daily_visit
from analytics.models import AnalyticsEvent
from analytics.services import track_event
from .services import grant_daily_login_rewards

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model."""
    
    verification_status = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()
    profile_thumbnail = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    has_usable_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'user_type',
            'is_verified',
            'is_test_user',
            'email',
            'first_name',
            'last_name',
            'external_user_id',
            'verification_status',
            'profile_picture',
            'profile_thumbnail',
            'avatar',
            'has_usable_password',
            'needs_username_setup',
            'agent_availability',
            'agent_status_note',
        ]
        read_only_fields = ['id']

    def get_verification_status(self, obj):
        from .models import VerificationRequest
        try:
            latest_request = VerificationRequest.objects.filter(user=obj).latest('created_at')
            return latest_request.status
        except VerificationRequest.DoesNotExist:
            return None

    def get_profile_picture(self, obj):
        if not obj.profile_picture:
            return None
        request = self.context.get('request')
        url = obj.profile_picture.url
        return build_public_absolute_uri(request, url)

    def get_profile_thumbnail(self, obj):
        if not obj.profile_thumbnail:
            return None
        request = self.context.get('request')
        url = obj.profile_thumbnail.url
        return build_public_absolute_uri(request, url)

    def get_avatar(self, obj):
        # Backward-compatible alias used by older app clients.
        return self.get_profile_thumbnail(obj) or self.get_profile_picture(obj)

    def get_has_usable_password(self, obj):
        return obj.has_usable_password()


class StaffUserListSerializer(UserSerializer):
    """User details exposed to staff user-management screens."""

    joined_at = serializers.DateTimeField(source='date_joined', read_only=True)

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + [
            'is_active',
            'is_staff',
            'is_superuser',
            'joined_at',
            'last_login',
        ]
        read_only_fields = fields


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

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom serializer to allow username-or-email login and include user data.
    """
    def validate(self, attrs):
        identifier = (attrs.get(self.username_field) or '').strip()
        if identifier:
            if '@' in identifier:
                user = User.objects.filter(email__iexact=identifier).only('username').first()
                if user:
                    attrs[self.username_field] = user.username
                else:
                    attrs[self.username_field] = identifier
            else:
                attrs[self.username_field] = identifier

        data = super().validate(attrs)
        record_daily_visit(self.user)
        grant_daily_login_rewards(self.user)
        request = self.context.get('request')
        track_event(
            request=request,
            user=self.user,
            event_type=AnalyticsEvent.EVENT_LOGIN,
            event_name='password_login',
            metadata={'method': 'password'},
        )

        data['user'] = UserSerializer(
            self.user,
            context=self.context,
        ).data
        return data


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for password change."""
    old_password = serializers.CharField(required=False, allow_blank=True)
    new_password = serializers.CharField(required=True, min_length=6)
    confirm_new_password = serializers.CharField(required=True)
    
    def validate(self, data):
        if data['new_password'] != data['confirm_new_password']:
            raise serializers.ValidationError({"confirm_new_password": "New passwords do not match."})
        return data


class CurrentPasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True, trim_whitespace=False)


class UsernameUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(
        required=True,
        min_length=3,
        max_length=150,
        validators=[UnicodeUsernameValidator()],
    )

    def validate_username(self, value):
        username = value.strip()
        if not username:
            raise serializers.ValidationError('Username cannot be empty.')

        user = self.context['request'].user
        queryset = User.objects.filter(username__iexact=username).exclude(pk=user.pk)
        if queryset.exists():
            raise serializers.ValidationError('This username is already taken.')
        return username


class AgentAvailabilityUpdateSerializer(serializers.Serializer):
    agent_availability = serializers.ChoiceField(
        choices=['online', 'busy', 'away', 'offline'],
        required=True,
    )
    agent_status_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=120,
    )


class ForgotPasswordInitiateSerializer(serializers.Serializer):
    """Serializer for initiating password reset."""
    email = serializers.EmailField(required=False)
    username = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        # Accept either `email` or `username`, normalize to `identifier`.
        identifier = data.get('email')
        if not identifier:
            identifier = data.get('username')
            if identifier:
                identifier = identifier.strip()

        if not identifier:
            raise serializers.ValidationError({
                'detail': 'Provide either email or username.'
            })

        data['identifier'] = identifier
        return data


class VerifyResetOTPSerializer(VerifyOTPSerializer):
    """Serializer for verifying reset OTP (reuses VerifyOTPSerializer structure)."""
    pass


class ProfilePictureUpdateSerializer(serializers.Serializer):
    profile_picture = serializers.ImageField(required=True)


class EmailChangeRequestSerializer(serializers.Serializer):
    new_email = serializers.EmailField(required=True)
    current_password = serializers.CharField(required=True, trim_whitespace=False)

    def validate_new_email(self, value):
        return value.strip().lower()


class EmailChangeVerifySerializer(serializers.Serializer):
    new_email = serializers.EmailField(required=True)
    otp_code = serializers.CharField(required=True, min_length=6, max_length=6)

    def validate_new_email(self, value):
        return value.strip().lower()

    def validate_otp_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("OTP code must contain only digits.")
        return value


class ResetPasswordCompleteSerializer(serializers.Serializer):
    """Serializer for completing password reset."""
    reset_token = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=6)
    confirm_new_password = serializers.CharField(required=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_new_password']:
            raise serializers.ValidationError({"confirm_new_password": "Passwords do not match."})
        return data


class GoogleLoginSerializer(serializers.Serializer):
    credential = serializers.CharField(required=True, trim_whitespace=False)


class HomeInfoSectionSerializer(serializers.ModelSerializer):
    points = serializers.SerializerMethodField()

    class Meta:
        model = HomeInfoSection
        fields = [
            'user_type',
            'title',
            'subtitle',
            'footer',
            'points',
            'is_active',
            'updated_at',
        ]

    def get_points(self, obj):
        points = obj.points.all().order_by('sort_order', 'id')
        return [
            {
                'icon': point.icon,
                'content': point.content,
            }
            for point in points
        ]
