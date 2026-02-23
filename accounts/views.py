from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from .serializers import RegisterSerializer, UserSerializer, VerifyOTPSerializer, VerifyUserIDSerializer
from .models import EmailVerificationOTP, VerificationRequest
from chat_project.utils import send_zeptomail, search_player

User = get_user_model()


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
        UserSerializer(request.user).data,
        status=status.HTTP_200_OK
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
        if not user.check_password(serializer.data.get('old_password')):
            return Response(
                {'old_password': ['Wrong password.']}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        user.set_password(serializer.data.get('new_password'))
        user.save()
        
        return Response(
            {'message': 'Password changed successfully'},
            status=status.HTTP_200_OK
        )
        
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
    
    # Mark OTP as used
    otp_record.is_used = True
    otp_record.save()
    
    # Generate tokens
    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken.for_user(user)
    
    return Response(
        {
            'message': 'Email verified successfully! You are now logged in.',
            'user': UserSerializer(user).data,
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
