from django.db import models
from django.conf import settings
from django.utils import timezone

class UserPresence(models.Model):
    STATUS_CHOICES = (
        ('ONLINE', 'Online'),
        ('IDLE', 'Idle'),
        ('OFFLINE', 'Offline'),
        ('DISCONNECTED', 'Disconnected'),
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='presence'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OFFLINE')
    socket_id = models.CharField(max_length=255, blank=True, null=True)
    last_seen = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.status}"

class PushToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_tokens'
    )
    fcm_token = models.TextField()
    device = models.CharField(max_length=255, blank=True)
    browser = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('user', 'fcm_token')

    def __str__(self):
        return f"Token for {self.user.username}"

class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    link = models.CharField(max_length=500, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} for {self.user.username}"

class MessageDelivery(models.Model):
    CHANNEL_CHOICES = (
        ('ws', 'WebSocket'),
        ('push', 'Push Notification'),
        ('email', 'Email'),
    )
    STATUS_CHOICES = (
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('seen', 'Seen'),
    )
    
    # Linked loosely string reference to avoid circular imports
    message = models.ForeignKey(
        'chat.Message',
        on_delete=models.CASCADE,
        related_name='delivery_status'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='message_deliveries'
    )
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='sent')
    timestamp = models.DateTimeField(auto_now_add=True)
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Msg {self.message_id} to {self.user.username} via {self.channel}: {self.status}"
