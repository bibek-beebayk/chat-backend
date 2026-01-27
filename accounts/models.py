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
    external_user_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        help_text="External user ID from another service for verification"
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
        help_text="Staff notes about verification"
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Verification Request'
        verbose_name_plural = 'Verification Requests'
    
    def __str__(self):
        return f"{self.user.username} - {self.external_user_id} ({self.status})"
    
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
        self.save()
        
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
                        <p>Reason: {self.notes if self.notes else 'No reason provided.'}</p>
                        <p>Please contact support if you have any questions.</p>
                    </body>
                </html>
                """
            )
        except Exception:
            pass  # Don't fail the transaction if email fails
