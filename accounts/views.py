from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from .serializers import RegisterSerializer, UserSerializer, VerifyOTPSerializer, VerifyUserIDSerializer
from .models import EmailVerificationOTP, VerificationRequest
from chat_project.utils import send_zeptomail

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
    
    # Check if user already has a pending verification request
    pending_request = VerificationRequest.objects.filter(
        user=user,
        status='pending'
    ).first()
    
    if pending_request:
        return Response(
            {'error': 'You already have a pending verification request. Please wait for staff approval.'},
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
    
    # Create verification request
    verification_request = VerificationRequest.objects.create(
        user=user,
        external_user_id=user_id,
        status='pending'
    )
    
    return Response(
        {
            'message': 'Verification request submitted successfully. Please wait for staff approval.',
            'status': 'pending',
            'request_id': verification_request.id
        },
        status=status.HTTP_201_CREATED
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
