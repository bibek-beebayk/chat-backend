from django.conf import settings
from django.db import models


class UserOnboardingState(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='social_onboarding_state',
    )
    has_seen_agent_suggestions = models.BooleanField(default=False)
    has_seen_player_suggestions = models.BooleanField(default=False)
    has_completed_social_onboarding = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    onboarding_version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user_id']

    def __str__(self):
        return f'Onboarding state for {self.user.username}'


class UserConnection(models.Model):
    TYPE_PLAYER_AGENT = 'player_agent'
    TYPE_PLAYER_PLAYER = 'player_player'
    TYPE_CHOICES = [
        (TYPE_PLAYER_AGENT, 'Player-Agent'),
        (TYPE_PLAYER_PLAYER, 'Player-Player'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_ACCEPTED = 'accepted'
    STATUS_REJECTED = 'rejected'
    STATUS_BLOCKED = 'blocked'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_BLOCKED, 'Blocked'),
    ]

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_connections',
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_connections',
    )
    connection_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    initiated_from_onboarding = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['requester', 'receiver', 'connection_type'],
                name='unique_connection_direction_per_type',
            ),
        ]

    def __str__(self):
        return f'{self.requester.username} -> {self.receiver.username} ({self.status})'

