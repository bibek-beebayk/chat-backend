from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from datetime import timedelta
import random
import string


class User(AbstractUser):
    """
    Custom User model with user_type field for role-based access control.
    """
    USER_TYPE_CHOICES = [
        ('player', 'Player'),
        ('agent', 'Agent'),
        ('staff', 'Staff'),
    ]
    AGENT_AVAILABILITY_CHOICES = [
        ('online', 'Online'),
        ('busy', 'Busy'),
        ('away', 'Away'),
        ('offline', 'Offline'),
    ]

    email = models.EmailField(
        unique=True,
        help_text='Required. Must be unique.'
    )
    
    user_type = models.CharField(
        max_length=10,
        choices=USER_TYPE_CHOICES,
        default='player',
        help_text='Type of user: player, agent, or staff'
    )

    is_verified = models.BooleanField(
        default=False,
        help_text='Designates whether this user has verified their account.'
    )
    is_test_user = models.BooleanField(
        default=False,
        help_text='Designates whether this account is isolated to test support rooms.'
    )
    external_user_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        help_text="External user ID from another service for verification"
    )
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        null=True,
        help_text='Optional user profile picture'
    )
    agent_availability = models.CharField(
        max_length=10,
        choices=AGENT_AVAILABILITY_CHOICES,
        default='online',
        help_text='Availability status used for direct player-to-agent chat.',
    )
    agent_status_note = models.CharField(
        max_length=120,
        blank=True,
        help_text='Optional short note shown to players (e.g. Back in 10 mins).',
    )
    
    def __str__(self):
        return f"{self.username} ({self.get_user_type_display()})"
    
    class Meta:
        ordering = ['username']


class EmailVerificationOTP(models.Model):
    """
    Model to store OTP codes for email verification during registration.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='verification_otps'
    )
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Email Verification OTP'
        verbose_name_plural = 'Email Verification OTPs'
    
    def __str__(self):
        return f"OTP for {self.user.email} - {self.otp_code}"
    
    def save(self, *args, **kwargs):
        # Set expiration time to 30 minutes from creation if not set
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=30)
        super().save(*args, **kwargs)
    
    def is_valid(self):
        """Check if OTP is valid (not expired, not used, and attempts < 3)"""
        return (
            not self.is_used and
            self.attempts < 3 and
            timezone.now() < self.expires_at
        )
    
    def increment_attempts(self):
        """Increment failed verification attempts"""
        self.attempts += 1
        self.save()
    
    @staticmethod
    def generate_otp():
        """Generate a random 6-digit OTP code"""
        return ''.join(random.choices(string.digits, k=6))


class EmailChangeOTP(models.Model):
    """
    Model to store OTP codes for authenticated email change verification.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='email_change_otps'
    )
    new_email = models.EmailField()
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Email Change OTP'
        verbose_name_plural = 'Email Change OTPs'

    def __str__(self):
        return f"Email change OTP for {self.user.email} -> {self.new_email}"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=30)
        super().save(*args, **kwargs)

    def is_valid(self):
        return (
            not self.is_used and
            self.attempts < 3 and
            timezone.now() < self.expires_at
        )

    def increment_attempts(self):
        self.attempts += 1
        self.save(update_fields=['attempts'])

    @staticmethod
    def generate_otp():
        return ''.join(random.choices(string.digits, k=6))


class VerificationRequest(models.Model):
    """
    Model to store user verification requests.
    Staff manually approve these after checking external sources.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='verification_requests',
        help_text="User requesting verification"
    )
    external_user_id = models.CharField(
        max_length=100,
        help_text="External user ID provided by user"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Request status"
    )
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verification_requests',
        help_text="Event related to this verification request"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the request was reviewed"
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_verification_requests',
        help_text="Staff member who reviewed this request"
    )
    notes = models.TextField(
        blank=True,
        help_text="Staff notes about verification",
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Verification Request'
        verbose_name_plural = 'Verification Requests'
    
    def __str__(self):
        return f"{self.user.username} - {self.status}"


class PlayerSearch(User):
    class Meta:
        proxy = True
        verbose_name = "Player Search"
        verbose_name_plural = "Player Search"
    
    def approve(self, reviewed_by_user):
        """Approve the verification request and verify the user"""
        from chat_project.utils import send_zeptomail
        from django.conf import settings

        self.user.is_verified = True
        self.user.external_user_id = self.external_user_id
        self.user.save()
        
        self.status = 'approved'
        self.reviewed_at = timezone.now()
        self.reviewed_by = reviewed_by_user
        self.reviewed_by = reviewed_by_user
        self.save()
        
        # If linked to an event, register the user
        if self.event:
            from events.models import EventRegistration
            EventRegistration.objects.get_or_create(
                user=self.user,
                event=self.event,
                defaults={'game_username': self.external_user_id}
            )
        
        # Send approval email
        try:
            send_zeptomail(
                self.user.email,
                'Account Verification Approved',
                f"""
                <html>
                    <body>
                        <p>Hello {self.user.username},</p>
                        <p>Your account verification request has been approved. You are now a verified user.</p>
                        <p>Thank you for playing with us!</p>
                    </body>
                </html>
                """
            )
        except Exception:
            pass  # Don't fail the transaction if email fails
    
    def reject(self, reviewed_by_user, notes=''):
        """Reject the verification request"""
        from chat_project.utils import send_zeptomail
        from django.conf import settings

        self.status = 'rejected'
        self.reviewed_at = timezone.now()
        self.reviewed_by = reviewed_by_user
        if notes:
            self.notes = notes
        self.save()
        
        # Send rejection email
        try:
            message = f'Hello {self.user.username},\n\nYour account verification request has been rejected.'
            if self.notes:
                message += f'\n\nReason: {self.notes}'
            message += '\n\nPlease contact support if you have any questions.'

            send_zeptomail(
                self.user.email,
                'Account Verification Update',
                f"""
                <html>
                    <body>
                        <p>Hello {self.user.username},</p>
                        <p>Your account verification request has been rejected.</p>
                        <p>Reason: {self.notes if self.notes else 'We could not find the game id you provided in our system.'}</p>
                        <p>Please contact support if you have any questions.</p>
                        <a href="https://community.hrlzone.com">Rollin Community</a>
                    </body>
                </html>
                """
            )
        except Exception:
            pass  # Don't fail the transaction if email fails

class AppVersion(models.Model):
    """
    Singleton model to track the most recent mandatory app version and hold the APK file.
    """
    version_code = models.CharField(
        max_length=20,
        help_text="The version string matching pubspec.yaml (e.g., '1.0.0+1')"
    )
    is_mandatory = models.BooleanField(
        default=True,
        help_text="Whether users are forced to update to this version"
    )
    release_notes = models.TextField(
        blank=True,
        help_text="Information about what is new in this release"
    )
    apk_file = models.FileField(
        upload_to='app_releases/',
        null=True,
        blank=True,
        help_text="The actual Android .apk file for download"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(
        default=True,
        help_text="If multiple versions exist, only the one marked is_active is served to clients."
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'App Release Version'
        verbose_name_plural = 'App Release Versions'

    def __str__(self):
        return f"App Version {self.version_code}"
    
    def save(self, *args, **kwargs):
        # Guarantee singleton-like active state
        if self.is_active:
            # We must commit it but prevent recursion or query errors if new
            AppVersion.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)


class HomeInfoSection(models.Model):
    """
    Role-specific home information content for mobile app users.
    Managed from Django admin and fetched by the app.
    """
    USER_TYPE_CHOICES = [
        ('player', 'Player'),
        ('agent', 'Agent'),
    ]

    user_type = models.CharField(
        max_length=10,
        choices=USER_TYPE_CHOICES,
        unique=True,
        help_text='Which user type should see this section.',
    )
    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=240, blank=True)
    footer = models.CharField(max_length=320, blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user_type']
        verbose_name = 'Home Info Section'
        verbose_name_plural = 'Home Info Sections'

    def __str__(self):
        return f"{self.get_user_type_display()} Home Info"


class HomeInfoPoint(models.Model):
    """
    Individual point entries for a HomeInfoSection.
    """
    section = models.ForeignKey(
        HomeInfoSection,
        on_delete=models.CASCADE,
        related_name='points',
    )
    icon = models.CharField(
        max_length=80,
        default='info_outline',
        help_text='Material icon name, e.g. verified_user_outlined',
    )
    content = models.CharField(max_length=240)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Home Info Point'
        verbose_name_plural = 'Home Info Points'

    def __str__(self):
        return f"{self.section.user_type}: {self.content[:40]}"
