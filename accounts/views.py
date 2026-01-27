from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import login, logout, get_user_model
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from .serializers import RegisterSerializer, LoginSerializer, UserSerializer, VerifyOTPSerializer
from .models import EmailVerificationOTP

User = get_user_model()


def send_otp_email(user, otp_code):
    """
    Helper function to send OTP email to user.
    """
    subject = 'Verify Your Account - OTP Code'
    message = f"""
Hello {user.username},

Thank you for registering! To complete your registration, please use the following One-Time Password (OTP):

OTP Code: {otp_code}

This code will expire in 30 minutes.

If you didn't request this code, please ignore this email.

Best regards,
The Team
    """
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Error sending OTP email: {str(e)}")
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


from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator

@api_view(['POST'])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def login_view(request):
    """
    Login user and create session.
    """
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']
        login(request, user)
        
        # Get new CSRF token after rotation
        from django.middleware.csrf import get_token
        token = get_token(request)
        
        return Response(
            {
                'message': 'Login successful',
                'user': UserSerializer(user).data,
                'csrfToken': token,
                'sessionKey': request.session.session_key
            },
            status=status.HTTP_200_OK
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """
    Logout user and destroy session.
    """
    logout(request)
    return Response(
        {'message': 'Logout successful'},
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@ensure_csrf_cookie
def current_user_view(request):
    """
    Get current authenticated user.
    """
    return Response(
        UserSerializer(request.user).data,
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def get_csrf_token(request):
    from django.middleware.csrf import get_token
    token = get_token(request)
    return Response({'success': 'CSRF cookie set', 'csrfToken': token})


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
        # Updating the password logs out all other sessions, but we want to keep this one?
        # Standard Django behavior cycles session key. 'login' function does this.
        # To prevent logout, we re-authenticate the session (Django < 3 requires manual update, > 3 handles it?)
        # For simplicity in DRF/Session auth, let's re-login the user to update the session hash.
        login(request, user)
        
        return Response(
            {'message': 'Password changed successfully'},
            status=status.HTTP_200_OK
        )
        
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
    
    # OTP is valid - activate user
    user.is_active = True
    user.is_verified = True
    user.save()
    
    # Mark OTP as used
    otp_record.is_used = True
    otp_record.save()
    
    # Log user in
    login(request, user)
    
    # Get CSRF token
    from django.middleware.csrf import get_token
    token = get_token(request)
    
    return Response(
        {
            'message': 'Email verified successfully! You are now logged in.',
            'user': UserSerializer(user).data,
            'csrfToken': token,
            'sessionKey': request.session.session_key
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
