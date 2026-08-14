from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils.text import slugify
from django.utils import timezone
from django.db.models import Q
from django.db import transaction
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from .serializers import (
    RegisterSerializer,
    UserSerializer,
    VerifyOTPSerializer,
    VerifyUserIDSerializer,
    HomeInfoSectionSerializer,
    ProfilePictureUpdateSerializer,
    EmailChangeRequestSerializer,
    EmailChangeVerifySerializer,
    CurrentPasswordSerializer,
    UsernameUpdateSerializer,
    AgentAvailabilityUpdateSerializer,
    GoogleLoginSerializer,
    StaffUserListSerializer,
)
from .models import (
    EmailVerificationOTP,
    EmailChangeOTP,
    VerificationRequest,
    HomeInfoSection,
)
from chat_project.utils import send_zeptomail, search_player
from rewards.services import record_daily_visit
from analytics.models import AnalyticsEvent
from analytics.services import track_event
from .services import grant_daily_login_rewards, grant_registration_rewards
from points.models import PointAction
from xp.models import XPAction

User = get_user_model()


def _is_staff_user(user):
    return bool(user and user.is_authenticated and getattr(user, 'user_type', None) == 'staff')


def send_otp_email(user, otp_code):
    """
    Helper function to send OTP email to user.
    """
    subject = 'Verify Your Account - OTP Code'
    message = f"""
    <html>
        <body>
            <p>Hello {user.username},</p>
            <p>Thank you for registering! To complete your registration, please use the following One-Time Password (OTP):</p>
            <h2 style="color: #4F46E5;">{otp_code}</h2>
            <p>This code will expire in 30 minutes.</p>
            <p>If you didn't request this code, please ignore this email.</p>
            <br>
            <p>Best regards,<br>The Team</p>
        </body>
    </html>
    """
    
    try:
        send_zeptomail(user.email, subject, message)
        return True
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error sending OTP email: {str(e)}", exc_info=True)
        return False


@api_view(['POST'])
@permission_classes([AllowAny])
def register_view(request):
    """
    Register a new user and send OTP for email verification.
    """
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        track_event(
            request=request,
            user=user,
            event_type=AnalyticsEvent.EVENT_REGISTER,
            event_name='registration_created',
            metadata={'user_type': user.user_type, 'email_sent': None},
        )
        
        # Generate OTP
        otp_code = EmailVerificationOTP.generate_otp()
        
        # Create OTP record
        EmailVerificationOTP.objects.create(
            user=user,
            otp_code=otp_code
        )
        
        # Send OTP email
        email_sent = send_otp_email(user, otp_code)
        
        if not email_sent:
            # If email fails, still return success but warn user
            return Response(
                {
                    'message': 'User registered but email sending failed. Please contact support.',
                    'email': user.email,
                    'email_sent': False
                },
                status=status.HTTP_201_CREATED
            )
        
        return Response(
            {
                'message': 'Registration successful! Please check your email for the OTP code.',
                'email': user.email,
                'email_sent': True
            },
            status=status.HTTP_201_CREATED
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import CustomTokenObtainPairSerializer

class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Login view that returns JWT tokens + user data.
    """
    serializer_class = CustomTokenObtainPairSerializer


def _build_jwt_login_response(user, request, message='Login successful.'):
    record_daily_visit(user)
    grant_daily_login_rewards(user)
    track_event(
        request=request,
        user=user,
        event_type=AnalyticsEvent.EVENT_LOGIN,
        event_name='google_login',
        metadata={'method': 'google'},
    )
    refresh = RefreshToken.for_user(user)
    return {
        'message': message,
        'user': UserSerializer(user, context={'request': request}).data,
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }


def _unique_google_username(email, name=''):
    local_part = email.split('@', 1)[0]
    base = slugify(name) or slugify(local_part) or 'google-user'
    base = base[:24].strip('-') or 'google-user'
    username = base
    suffix = 1
    while User.objects.filter(username__iexact=username).exists():
        suffix += 1
        username = f'{base[:20]}-{suffix}'
    return username


@api_view(['POST'])
@permission_classes([AllowAny])
def google_login_view(request):
    serializer = GoogleLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    client_ids = getattr(settings, 'GOOGLE_OAUTH_CLIENT_IDS', [])
    if not client_ids:
        return Response(
            {'error': 'Google login is not configured.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    credential = serializer.validated_data['credential']
    token_info = None
    last_error = None

    for client_id in client_ids:
        try:
            token_info = id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                client_id,
            )
            break
        except ValueError as exc:
            last_error = exc

    if token_info is None:
        return Response(
            {'error': 'Invalid Google credential.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    email = (token_info.get('email') or '').strip().lower()
    if not email:
        return Response(
            {'error': 'Google account did not provide an email address.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if token_info.get('email_verified') is not True:
        return Response(
            {'error': 'Google email address is not verified.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        user = User.objects.filter(email__iexact=email).first()
        created = False

        if user is None:
            full_name = token_info.get('name') or ''
            user = User.objects.create_user(
                username=_unique_google_username(email, full_name),
                email=email,
                password=None,
                user_type='player',
                first_name=(token_info.get('given_name') or '')[:150],
                last_name=(token_info.get('family_name') or '')[:150],
                needs_username_setup=True,
            )
            created = True

        update_fields = []
        if not user.is_active:
            user.is_active = True
            update_fields.append('is_active')
        if not user.first_name and token_info.get('given_name'):
            user.first_name = token_info.get('given_name')[:150]
            update_fields.append('first_name')
        if not user.last_name and token_info.get('family_name'):
            user.last_name = token_info.get('family_name')[:150]
            update_fields.append('last_name')
        if update_fields:
            user.save(update_fields=update_fields)

    if created:
        track_event(
            request=request,
            user=user,
            event_type=AnalyticsEvent.EVENT_REGISTER,
            event_name='google_registration',
            metadata={'user_type': user.user_type, 'method': 'google'},
        )
        try:
            grant_registration_rewards(user)
        except (PointAction.DoesNotExist, XPAction.DoesNotExist) as exc:
            import logging
            logging.getLogger(__name__).error('Registration reward grant failed for user %s: %s', user.id, exc)

    return Response(
        _build_jwt_login_response(
            user,
            request,
            message='Google account connected.' if created else 'Login successful.',
        ),
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """
    Logout user by blacklisting the refresh token.
    """
    try:
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"error": "Refresh token is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        token = RefreshToken(refresh_token)
        token.blacklist()
        track_event(
            request=request,
            user=request.user,
            event_type=AnalyticsEvent.EVENT_LOGOUT,
            event_name='logout',
        )
        return Response({'message': 'Logout successful'}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user_view(request):
    """
    Get current authenticated user.
    """
    return Response(
        UserSerializer(request.user, context={'request': request}).data,
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def staff_users_view(request):
    """
    Return a filterable user-management list for staff users.
    """
    if not _is_staff_user(request.user):
        return Response(
            {'error': 'Only staff users can view user management.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    queryset = User.objects.all().order_by('-date_joined', 'username')
    user_type = request.query_params.get('user_type', '').strip()
    status_filter = request.query_params.get('status', '').strip()
    search = request.query_params.get('search', '').strip()

    if user_type in {'player', 'agent', 'staff'}:
        queryset = queryset.filter(user_type=user_type)

    if status_filter == 'active':
        queryset = queryset.filter(is_active=True)
    elif status_filter == 'inactive':
        queryset = queryset.filter(is_active=False)
    elif status_filter == 'verified':
        queryset = queryset.filter(is_verified=True)
    elif status_filter == 'unverified':
        queryset = queryset.filter(is_verified=False)
    elif status_filter == 'test':
        queryset = queryset.filter(is_test_user=True)

    if search:
        queryset = queryset.filter(
            Q(username__icontains=search)
            | Q(email__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(external_user_id__icontains=search)
        )

    try:
        limit = min(max(int(request.query_params.get('limit', 50)), 1), 100)
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = max(int(request.query_params.get('offset', 0)), 0)
    except (TypeError, ValueError):
        offset = 0

    total_count = queryset.count()
    users = queryset[offset:offset + limit]
    stats_queryset = User.objects.all()
    stats = {
        'total': stats_queryset.count(),
        'players': stats_queryset.filter(user_type='player').count(),
        'agents': stats_queryset.filter(user_type='agent').count(),
        'staff': stats_queryset.filter(user_type='staff').count(),
        'active': stats_queryset.filter(is_active=True).count(),
        'verified': stats_queryset.filter(is_verified=True).count(),
        'test': stats_queryset.filter(is_test_user=True).count(),
    }

    return Response({
        'results': StaffUserListSerializer(users, many=True, context={'request': request}).data,
        'meta': {
            'count': total_count,
            'limit': limit,
            'offset': offset,
            'has_more': offset + limit < total_count,
        },
        'stats': stats,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def home_info_view(request):
    """
    Return role-specific home info content for player/agent users.
    """
    user_type = getattr(request.user, 'user_type', None)
    if user_type not in ('player', 'agent'):
        return Response({}, status=status.HTTP_200_OK)

    section = HomeInfoSection.objects.filter(
        user_type=user_type,
        is_active=True,
    ).first()
    if not section:
        return Response({}, status=status.HTTP_200_OK)

    return Response(
        HomeInfoSectionSerializer(section).data,
        status=status.HTTP_200_OK,
    )


def _send_email_change_otp(user, new_email, otp_code):
    subject = 'Confirm Your Email Change - OTP Code'
    message = f"""
    <html>
        <body>
            <p>Hello {user.username},</p>
            <p>Use the following OTP to confirm your new email address:</p>
            <h2 style="color: #4F46E5;">{otp_code}</h2>
            <p>This code will expire in 30 minutes.</p>
            <p>If you did not request this change, ignore this email.</p>
        </body>
    </html>
    """
    send_zeptomail(new_email, subject, message)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_profile_picture_view(request):
    serializer = ProfilePictureUpdateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    request.user.profile_picture = serializer.validated_data['profile_picture']
    request.user.save(update_fields=['profile_picture'])
    return Response(
        {
            'message': 'Profile picture updated successfully.',
            'user': UserSerializer(request.user, context={'request': request}).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_username_view(request):
    serializer = UsernameUpdateSerializer(
        data=request.data,
        context={'request': request},
    )
    if not serializer.is_valid():
        first_error = next(iter(serializer.errors.values()), ['Invalid username.'])
        if isinstance(first_error, list) and first_error:
            error_message = str(first_error[0])
        else:
            error_message = 'Invalid username.'
        return Response(
            {
                'error': error_message,
                'errors': serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = request.user
    user.username = serializer.validated_data['username']
    user.needs_username_setup = False
    user.save(update_fields=['username', 'needs_username_setup'])
    return Response(
        {
            'message': 'Username updated successfully.',
            'user': UserSerializer(user, context={'request': request}).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_email_change_view(request):
    serializer = EmailChangeRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    new_email = serializer.validated_data['new_email']
    current_password = serializer.validated_data['current_password']
    current_email = (user.email or '').strip().lower()

    if not user.check_password(current_password):
        return Response(
            {'error': 'Current password is incorrect.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if new_email == current_email:
        return Response(
            {'error': 'New email must be different from current email.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    email_taken = User.objects.filter(email__iexact=new_email).exclude(id=user.id).exists()
    if email_taken:
        return Response(
            {'error': 'The email is already in use. Please use a different one.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    EmailChangeOTP.objects.filter(user=user, new_email__iexact=new_email, is_used=False).update(is_used=True)
    otp_code = EmailChangeOTP.generate_otp()
    EmailChangeOTP.objects.create(
        user=user,
        new_email=new_email,
        otp_code=otp_code,
    )

    try:
        _send_email_change_otp(user, new_email, otp_code)
    except Exception:
        return Response(
            {'error': 'Failed to send OTP email. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(
        {'message': 'OTP sent to new email address.', 'new_email': new_email},
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_email_change_view(request):
    serializer = EmailChangeVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    new_email = serializer.validated_data['new_email']
    otp_code = serializer.validated_data['otp_code']

    email_taken = User.objects.filter(email__iexact=new_email).exclude(id=user.id).exists()
    if email_taken:
        return Response(
            {'error': 'The email is already in use. Please use a different one.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        otp_record = EmailChangeOTP.objects.filter(
            user=user,
            new_email__iexact=new_email,
            is_used=False,
        ).latest('created_at')
    except EmailChangeOTP.DoesNotExist:
        return Response(
            {'error': 'Invalid OTP code.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not otp_record.is_valid():
        if otp_record.is_used:
            return Response(
                {'error': 'This OTP code has already been used.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if otp_record.attempts >= 3:
            return Response(
                {'error': 'Maximum verification attempts exceeded. Please request a new OTP.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timezone.now() > otp_record.expires_at:
            return Response(
                {'error': 'This OTP code has expired. Please request a new one.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    if otp_record.otp_code != otp_code:
        otp_record.increment_attempts()
        remaining_attempts = 3 - otp_record.attempts
        return Response(
            {'error': f'Invalid OTP code. {remaining_attempts} attempts remaining.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        user.email = new_email
        user.save(update_fields=['email'])
        otp_record.is_used = True
        otp_record.save(update_fields=['is_used'])
        EmailChangeOTP.objects.filter(
            user=user,
            new_email__iexact=new_email,
            is_used=False,
        ).exclude(id=otp_record.id).update(is_used=True)

    return Response(
        {
            'message': 'Email changed successfully.',
            'user': UserSerializer(user, context={'request': request}).data,
        },
        status=status.HTTP_200_OK,
    )





@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    """
    Change user password.
    """
    from .serializers import ChangePasswordSerializer
    
    serializer = ChangePasswordSerializer(data=request.data)
    if serializer.is_valid():
        user = request.user
        if user.has_usable_password() and not user.check_password(serializer.data.get('old_password', '')):
            return Response(
                {'old_password': ['Wrong password.']}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        user.set_password(serializer.data.get('new_password'))
        user.save()
        
        return Response(
            {
                'message': 'Password changed successfully',
                'user': UserSerializer(user, context={'request': request}).data,
            },
            status=status.HTTP_200_OK
        )
        
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_current_password_view(request):
    serializer = CurrentPasswordSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    current_password = serializer.validated_data['current_password']
    if not request.user.check_password(current_password):
        return Response(
            {'error': 'Current password is incorrect.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {'message': 'Password verified.'},
        status=status.HTTP_200_OK,
    )


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_agent_availability_view(request):
    user = request.user
    if user.user_type != 'agent':
        return Response(
            {'error': 'Only agents can update availability.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = AgentAvailabilityUpdateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user.agent_availability = serializer.validated_data['agent_availability']
    user.agent_status_note = serializer.validated_data.get('agent_status_note', '').strip()
    user.save(update_fields=['agent_availability', 'agent_status_note'])

    return Response(
        {
            'message': 'Availability updated successfully.',
            'user': UserSerializer(user, context={'request': request}).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_account_view(request):
    """
    Permanently delete the authenticated user's account and related data.
    """
    user = request.user

    # Safety guard to prevent accidental deletion of Django superuser accounts.
    if user.is_superuser:
        return Response(
            {'error': 'Superuser account cannot be deleted from this endpoint.'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        with transaction.atomic():
            user.delete()
        return Response(
            {'message': 'Account deleted successfully.'},
            status=status.HTTP_200_OK
        )
    except Exception:
        return Response(
            {'error': 'Failed to delete account. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initiate_verification_request_view(request):
    """
    Generate and send an OTP for user ID verification.
    """
    user = request.user
    
    # Check if user is already verified
    if user.is_verified:
        return Response(
            {'error': 'Your account is already verified.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check if user already has a pending verification request
    pending_request = VerificationRequest.objects.filter(
        user=user,
        status='pending'
    ).first()
    
    if pending_request:
        return Response(
            {'error': 'You already have a pending verification request.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Clean up old unused OTPs
    EmailVerificationOTP.objects.filter(
        user=user,
        is_used=False
    ).delete()
    
    # Generate new OTP
    otp_code = EmailVerificationOTP.generate_otp()
    EmailVerificationOTP.objects.create(
        user=user,
        otp_code=otp_code
    )
    
    # Send email
    subject = 'Verify Your User ID Request'
    message = f"""
    <html>
        <body>
            <p>Hello,</p>
            <p>Your OTP code for verification request is:</p>
            <h2 style="color: #4F46E5;">{otp_code}</h2>
        </body>
    </html>
    """
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user.email]
    
    try:
        send_zeptomail(user.email, subject, message)
        return Response({'message': 'OTP sent to your email.'}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response(
            {'error': 'Failed to send email. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp_view(request):
    """
    Verify OTP code and activate user account.
    """
    serializer = VerifyOTPSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    email = serializer.validated_data['email']
    otp_code = serializer.validated_data['otp_code']
    
    # Find user by email
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response(
            {'error': 'No user found with this email address.'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Check if user is already active
    if user.is_active:
        return Response(
            {'error': 'This account is already verified.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Find the latest valid OTP for this user
    try:
        otp_record = EmailVerificationOTP.objects.filter(
            user=user,
            otp_code=otp_code
        ).latest('created_at')
    except EmailVerificationOTP.DoesNotExist:
        return Response(
            {'error': 'Invalid OTP code.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check if OTP is valid
    if not otp_record.is_valid():
        if otp_record.is_used:
            return Response(
                {'error': 'This OTP code has already been used.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        elif otp_record.attempts >= 3:
            return Response(
                {'error': 'Maximum verification attempts exceeded. Please request a new OTP.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        elif timezone.now() > otp_record.expires_at:
            return Response(
                {'error': 'This OTP code has expired. Please request a new one.'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    # Verify OTP code matches
    if otp_record.otp_code != otp_code:
        otp_record.increment_attempts()
        remaining_attempts = 3 - otp_record.attempts
        return Response(
            {'error': f'Invalid OTP code. {remaining_attempts} attempts remaining.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # OTP is valid - activate user (but keep unverified until user ID verification)
    user.is_active = True
    user.save()
    track_event(
        request=request,
        user=user,
        event_type=AnalyticsEvent.EVENT_REGISTER,
        event_name='email_verified',
        metadata={'user_type': user.user_type},
    )

    # Mark OTP as used
    otp_record.is_used = True
    otp_record.save()

    if user.user_type == 'player':
        try:
            grant_registration_rewards(user)
        except (PointAction.DoesNotExist, XPAction.DoesNotExist) as exc:
            import logging
            logging.getLogger(__name__).error('Registration reward grant failed for user %s: %s', user.id, exc)

    # Generate tokens
    from rest_framework_simplejwt.tokens import RefreshToken
    record_daily_visit(user)
    refresh = RefreshToken.for_user(user)
    
    return Response(
        {
            'message': 'Email verified successfully! You are now logged in.',
            'user': UserSerializer(user, context={'request': request}).data,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        },
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def resend_otp_view(request):
    """
    Resend OTP code to user's email.
    """
    email = request.data.get('email')
    
    if not email:
        return Response(
            {'error': 'Email address is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Find user by email
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response(
            {'error': 'No user found with this email address.'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Check if user is already active
    if user.is_active:
        return Response(
            {'error': 'This account is already verified.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Invalidate old OTP codes for this user
    EmailVerificationOTP.objects.filter(user=user, is_used=False).update(is_used=True)
    
    # Generate new OTP
    otp_code = EmailVerificationOTP.generate_otp()
    
    # Create new OTP record
    EmailVerificationOTP.objects.create(
        user=user,
        otp_code=otp_code
    )
    
    # Send OTP email
    email_sent = send_otp_email(user, otp_code)
    
    if not email_sent:
        return Response(
            {'error': 'Failed to send email. Please try again later.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    return Response(
        {'message': 'A new OTP code has been sent to your email.'},
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_user_id_view(request):
    """
    Submit a verification request with external user ID.
    Requires OTP verification.
    """
    serializer = VerifyUserIDSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    user = request.user
    user_id = serializer.validated_data['user_id']
    otp_code = serializer.validated_data['otp']
    
    # Check if user is already verified
    if user.is_verified:
        return Response(
            {'error': 'Your account is already verified.'},
            status=status.HTTP_400_BAD_REQUEST
        )

        
    # Verify OTP
    try:
        otp_record = EmailVerificationOTP.objects.filter(
            user=user,
            otp_code=otp_code,
            is_used=False
        ).latest('created_at')
        
        if not otp_record.is_valid():
            return Response(
                {'error': 'OTP has expired. Please request a new one.'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Mark OTP as used
        otp_record.is_used = True
        otp_record.save()
        
    except EmailVerificationOTP.DoesNotExist:
        return Response(
            {'error': 'Invalid OTP.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check if the user_id is already associated to existing user
    if User.objects.filter(external_user_id=user_id).exists():
        return Response(
            {'message': 'This user_id is already associated with another account. Please contact support.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    res = search_player(user_id)
    
    if res:
        user.is_verified = True
        user.external_user_id = user_id
        user.save()
        return Response(
            {
                'message': 'Your verification was successful.',
                'status': 'verified',
            },
            status=status.HTTP_200_OK
        )
    
    return Response(
            {
                'message': 'We could not find the game id you provided. Please Contact Support.',
                'status': 'not verified',
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    
from chat_project.utils import send_zeptomail
@api_view(['POST'])
@permission_classes([AllowAny])
def test_email_view(request):
    """
    Test email sending functionality.
    """
    email = request.data.get('email')
    
    if not email:
        return Response(
            {'error': 'Email address is required.'},
            status=status.HTTP_400_BAD_REQUEST
        )
        
    subject = 'Test Email from ZeptoMail'
    message = 'This is a test email sent from the application to verify ZeptoMail integration.'
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [email]
    
    try:
        # send_mail(
        #     subject=subject,
        #     message=message,
        #     from_email=from_email,
        #     recipient_list=recipient_list,
        #     fail_silently=False,
        # )
        send_zeptomail(email, subject, message)
        return Response(
            {'message': f'Test email sent successfully to {email}'},
            status=status.HTTP_200_OK
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error sending test email: {str(e)}", exc_info=True)
        return Response(
            {'error': f'Failed to send email: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Forgot Password Views

@api_view(['POST'])
@permission_classes([AllowAny])
def initiate_password_reset_view(request):
    """
    Step 1: Initiate password reset by sending OTP to email.
    """
    from .serializers import ForgotPasswordInitiateSerializer
    
    serializer = ForgotPasswordInitiateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    identifier = serializer.validated_data['identifier']

    user = User.objects.filter(
        Q(email__iexact=identifier) | Q(username__iexact=identifier)
    ).first()
    if not user:
        # Security: Don't reveal if user exists or not, or simply return 404 if less security concern
        # For better UX in this context, we'll return 404 to let user know to register
        return Response(
            {'error': 'No account found with this email or username.'},
            status=status.HTTP_404_NOT_FOUND
        )
        
    # Generate and send OTP
    # Clean up old unused OTPs
    EmailVerificationOTP.objects.filter(user=user, is_used=False).delete()
    
    otp_code = EmailVerificationOTP.generate_otp()
    EmailVerificationOTP.objects.create(user=user, otp_code=otp_code)
    
    # Send Email
    subject = 'Reset Your Password - OTP Code'
    message = f"""
    <html>
        <body>
            <p>Hello {user.username},</p>
            <p>You requested to reset your password. Use the code below to proceed:</p>
            <h2 style="color: #ea580c;">{otp_code}</h2>
            <p>This code expires in 30 minutes.</p>
        </body>
    </html>
    """
    
    try:
        send_zeptomail(user.email, subject, message)
        return Response({'message': 'OTP code sent to your email.'}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': 'Failed to send OTP email.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_reset_otp_view(request):
    """
    Step 2: Verify OTP and return a signed reset token.
    """
    from .serializers import VerifyResetOTPSerializer
    from django.core.signing import TimestampSigner
    
    serializer = VerifyResetOTPSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    email = serializer.validated_data['email']
    otp_code = serializer.validated_data['otp_code']
    
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        
    try:
        otp_record = EmailVerificationOTP.objects.filter(
            user=user, otp_code=otp_code, is_used=False
        ).latest('created_at')
    except EmailVerificationOTP.DoesNotExist:
        return Response({'error': 'Invalid OTP.'}, status=status.HTTP_400_BAD_REQUEST)
        
    if not otp_record.is_valid():
        return Response({'error': 'OTP expired or invalid.'}, status=status.HTTP_400_BAD_REQUEST)
        
    if otp_record.otp_code != otp_code:
        otp_record.increment_attempts()
        return Response({'error': 'Invalid OTP.'}, status=status.HTTP_400_BAD_REQUEST)
        
    # OTP Valid: Mark as used
    otp_record.is_used = True
    otp_record.save()
    
    # Generate Signed Token (valid for 10 minutes)
    signer = TimestampSigner()
    # Sign the user ID
    reset_token = signer.sign(str(user.id))
    
    return Response({
        'message': 'OTP Verified.',
        'reset_token': reset_token
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password_complete_view(request):
    """
    Step 3: Reset password using the token.
    """
    from .serializers import ResetPasswordCompleteSerializer
    from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
    
    serializer = ResetPasswordCompleteSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
    reset_token = serializer.validated_data['reset_token']
    new_password = serializer.validated_data['new_password']
    
    signer = TimestampSigner()
    try:
        # Verify token (max age 10 mins = 600 seconds)
        user_id = signer.unsign(reset_token, max_age=600)
    except SignatureExpired:
        return Response({'error': 'Reset session expired. Please start over.'}, status=status.HTTP_400_BAD_REQUEST)
    except BadSignature:
        return Response({'error': 'Invalid reset token.'}, status=status.HTTP_400_BAD_REQUEST)
        
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        
    # Set new password
    user.set_password(new_password)
    user.save()
    
    # Auto-login? Or just success message?
    # Let's just return success and let them login
    return Response({'message': 'Password has been reset successfully. Please login with your new password.'}, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([AllowAny])
def latest_app_version_view(request):
    """
    Returns the currently active latest App Version configuration.
    """
    from .models import AppVersion
    
    version = AppVersion.objects.filter(is_active=True).first()
    
    if not version:
        return Response({
            'version_code': '1.0.0+1',
            'is_mandatory': False,
            'release_notes': '',
            'apk_url': None
        }, status=status.HTTP_200_OK)
        
    apk_url = None
    if version.apk_file:
        apk_url = request.build_absolute_uri(version.apk_file.url)
        
    return Response({
        'version_code': version.version_code,
        'is_mandatory': version.is_mandatory,
        'release_notes': version.release_notes,
        'apk_url': apk_url
    }, status=status.HTTP_200_OK)
