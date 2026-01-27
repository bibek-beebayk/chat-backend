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
