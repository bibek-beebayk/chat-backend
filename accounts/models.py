from django.db import models
from django.contrib.auth.models import AbstractUser


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
    
    def __str__(self):
        return f"{self.username} ({self.get_user_type_display()})"
    
    class Meta:
        ordering = ['username']
