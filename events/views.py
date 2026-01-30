from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

from .models import Event, EventRegistration
from .serializers import EventSerializer, RegisterInitSerializer, VerifyEventOTPSerializer
from accounts.models import EmailVerificationOTP
from accounts.views import send_otp_email
from chat_project.utils import send_zeptomail
from django.conf import settings

User = get_user_model()

# Placeholder URLs - In production these should come from settings or env
MAIN_WEBSITE_URL = settings.MAIN_WEBSITE_URL

from django.utils import timezone

@api_view(['GET'])
@permission_classes([AllowAny])
def get_latest_event(request):
    now = timezone.now()
    event = Event.objects.filter(start_date__lte=now, end_date__gte=now).order_by('-start_date').first()
    if event:
        serializer = EventSerializer(event)
        data = serializer.data.copy() # Make mutable
        
        # Check registration status if user is authenticated
        if request.user.is_authenticated:
            print(f"DEBUG: User {request.user.username} is authenticated")
            data['is_registered'] = EventRegistration.objects.filter(user=request.user, event=event).exists()
            
            from .models import EligibilityCheckRequest
            try:
                latest_request = EligibilityCheckRequest.objects.filter(user=request.user, event=event).latest('created_at')
                data['eligibility_status'] = latest_request.status
                print(f"DEBUG: Found eligibility request: {latest_request.status}")
            except EligibilityCheckRequest.DoesNotExist:
                data['eligibility_status'] = None
                print("DEBUG: No eligibility request found")
        else:
            print("DEBUG: User is NOT authenticated")
            data['is_registered'] = False
            data['eligibility_status'] = None
            
        return Response(data)
    return Response({'message': 'No active events'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
@permission_classes([AllowAny])
def get_active_events(request):
    now = timezone.now()
    events = Event.objects.filter(start_date__lte=now, end_date__gte=now).order_by('start_date')
    serializer = EventSerializer(events, many=True, context={'request': request})
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([AllowAny])
def register_init_view(request):
    serializer = RegisterInitSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        username = serializer.validated_data['username']
        event_id = serializer.validated_data.get('event_id')
        
        # Check if user exists by email or username
        user = User.objects.filter(email=email).first()
        if not user:
            user = User.objects.filter(username=username).first()
            
        # Check for existing registration
        if user and event_id:
            if EventRegistration.objects.filter(user=user, event_id=event_id).exists():
                # Send Event Link Email
                event_link = f"{MAIN_WEBSITE_URL}/events/{event_id}"
                
                subject = "Access Your Event"
                message = f"""
                <html>
                    <body>
                        <p>Hello {user.username},</p>
                        <p>You are already registered for this event.</p>
                        <p>Click the link below to access the event page:</p>
                        <p><a href="{event_link}" style="padding: 10px 20px; background-color: #ffd700; color: #000; text-decoration: none; border-radius: 5px;">Go to Event Page</a></p>
                    </body>
                </html>
                """
                send_zeptomail(user.email, subject, message)

                return Response({
                    'status': 'already_registered',
                    'message': 'You are already registered. We have sent the event link to your email.'
                }, status=status.HTTP_200_OK)

        if not user:
            # Create new inactive user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=None, # Unusable password
                is_active=False
            )
            # IMPORTANT: We might need to ensure username uniqueness if it clashed above but fell through
            # For this simple flow, we assume create_user handles uniqueness constraint (it raises IntegrityError)
            
        # Generate OTP
        EmailVerificationOTP.objects.filter(user=user, is_used=False).delete()
        otp_code = EmailVerificationOTP.generate_otp()
        EmailVerificationOTP.objects.create(user=user, otp_code=otp_code)
        
        # Send Email
        send_otp_email(user, otp_code)
        
        return Response({
            'status': 'otp_sent',
            'email': email
        })
        
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_event_otp_view(request):
    serializer = VerifyEventOTPSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        otp_code = serializer.validated_data['otp_code']
        event_id = serializer.validated_data.get('event_id')
        
        user = get_object_or_404(User, email=email)
        
        # Verify OTP
        try:
            otp_record = EmailVerificationOTP.objects.filter(
                user=user, otp_code=otp_code, is_used=False
            ).latest('created_at')
            
            if not otp_record.is_valid():
                return Response({'error': 'Invalid or expired OTP'}, status=status.HTTP_400_BAD_REQUEST)
                
            otp_record.is_used = True
            otp_record.save()
            
        except EmailVerificationOTP.DoesNotExist:
             return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
             


        # Determine Flow Phase 2
        # If user has a usable password and is active -> Existing User -> Send Event Link
        # If user has no usable password or is inactive -> New User -> Send Set Password Link
        
        event_link = f"{MAIN_WEBSITE_URL}/events"
        if event_id:
            event_link += f"/{event_id}"
            
        if user.has_usable_password() and user.is_active:
            # Send Event Link Email (Login Link)
            subject = "Access Your Event Dashboard"
            message = f"""
            <html>
                <body>
                    <p>Hello {user.username},</p>
                    <p>You have successfully verified your identity.</p>
                    <p>Please log in to complete your registration for the event.</p>
                    <p><a href="{event_link}" style="padding: 10px 20px; background-color: #ffd700; color: #000; text-decoration: none; border-radius: 5px;">Go to Event Page</a></p>
                </body>
            </html>
            """
            send_zeptomail(user.email, subject, message)
            
        else:
            # New User -> Activate & Send Set Password Link
            user.is_active = True
            user.save()
            
            # Generate Reset Token
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            set_password_link = f"{MAIN_WEBSITE_URL}/set-password?uid={uid}&token={token}&next={event_link}"
            
            subject = "Complete Your Account Setup"
            message = f"""
            <html>
                <body>
                    <p>Hello {user.username},</p>
                    <p>Welcome! Please set your password to complete your account setup and proceed to the event page.</p>
                    <p><a href="{set_password_link}" style="padding: 10px 20px; background-color: #ffd700; color: #000; text-decoration: none; border-radius: 5px;">Set Password</a></p>
                </body>
            </html>
            """
            send_zeptomail(user.email, subject, message)
            
        return Response({
            'status': 'success',
            'message': 'Verification successful. Please check your email for the next steps.',
            'is_existing_user': user.has_usable_password() and user.is_active,
            'redirect_url': event_link if (user.has_usable_password() and user.is_active) else None
        })
            
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


from rest_framework.permissions import IsAuthenticated

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def register_for_event_view(request):
    """
    Manually register an authenticated user for an event.
    Requires user to be verified.
    """
    event_id = request.data.get('event_id')
    if not event_id:
        return Response({'error': 'Event ID is required.'}, status=status.HTTP_400_BAD_REQUEST)
        
    user = request.user
    
    # 1. Check Verification
    if not user.is_verified:
        return Response({
            'error': 'User could not be verified. Please go through the verification requirements and try again.'
        }, status=status.HTTP_400_BAD_REQUEST)
        
    # 2. Check duplicate registration
    if EventRegistration.objects.filter(user=user, event_id=event_id).exists():
         return Response({'error': 'You are already registered for this event.'}, status=status.HTTP_400_BAD_REQUEST)
         
    # 3. Create Registration
    EventRegistration.objects.create(
        user=user,
        event_id=event_id,
        game_username=user.username
    )
    
    return Response({
        'status': 'success',
        'message': 'You are successfully registered!'
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_eligibility_view(request):
    """
    Create an eligibility check request.
    """
    print(f"DEBUG check_eligibility: {request.data}")
    event_id = request.data.get('event_id')
    print(f"DEBUG event_id: {event_id}")
    if not event_id:
        return Response({'error': 'Event ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

    event = get_object_or_404(Event, id=event_id)
    from .models import EligibilityCheckRequest
    
    # Check if request already exists
    eligibility_request, created = EligibilityCheckRequest.objects.get_or_create(
        user=request.user,
        event=event
    )
    
    if eligibility_request.status == 'approved':
         # If already approved, return eligible
         return Response({'eligible': True})
         
    if eligibility_request.status == 'rejected':
         # Reset to pending for retry
         eligibility_request.status = 'pending'
         eligibility_request.save()

    return Response({
        'message': 'Your eligibility is being checked. Please check back in a while.',
        'status': 'pending'
    })


from .serializers import SetPasswordSerializer
from django.utils.http import urlsafe_base64_decode
from rest_framework_simplejwt.tokens import RefreshToken

@api_view(['POST'])
@permission_classes([AllowAny])
def set_password_view(request):
    serializer = SetPasswordSerializer(data=request.data)
    if serializer.is_valid():
        uidb64 = serializer.validated_data['uid']
        token = serializer.validated_data['token']
        password = serializer.validated_data['password']

        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
             return Response({'error': 'Invalid user.'}, status=status.HTTP_400_BAD_REQUEST)

        if default_token_generator.check_token(user, token):
            user.set_password(password)
            user.is_active = True
            user.save()
            
            # Auto-Login (Generate JWT)
            refresh = RefreshToken.for_user(user)

            return Response({
                'status': 'success',
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': {
                    'username': user.username,
                    'email': user.email
                }
            })
        else:
             return Response({'error': 'Invalid or expired token.'}, status=status.HTTP_400_BAD_REQUEST)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
