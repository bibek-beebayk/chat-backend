from django.db import models
from django.conf import settings


class SupportRoom(models.Model):
    """
    A workstation/queue for staff.
    Staff members enter this room to start their shift and receive chats.
    """
    ROOM_TYPES = (
        ('player', 'Player Support'),
        ('agent', 'Agent Support'),
        ('event', 'Event Support'),
        ('all', 'General Support'),
    )
    name = models.CharField(max_length=100)
    room_type = models.CharField(max_length=10, choices=ROOM_TYPES, default='all')
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='active_support_rooms',
        limit_choices_to={'user_type': 'staff'}
    )
    is_active = models.BooleanField(default=False)
    is_test_room = models.BooleanField(
        default=False,
        help_text='If true, this support room is visible only to test users/staff.'
    )

    def __str__(self):
        status = f"Occupied by {self.staff.username}" if self.staff else "Empty"
        prefix = "[TEST] " if self.is_test_room else ""
        return f"{prefix}{self.name} ({status})"


class Room(models.Model):
    """
    Chat room model. Each room is assigned to one staff member.
    """
    name = models.CharField(max_length=100, blank=True)
    client = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='support_room',
        limit_choices_to={'user_type__in': ['player', 'agent']},
        null=True,
        blank=True
    )
    current_handler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_rooms',
        limit_choices_to={'user_type': 'staff'}
    )
    queue = models.ForeignKey(
        'SupportRoom',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='queued_chats'
    )
    is_test_room = models.BooleanField(
        default=False,
        help_text='If true, this chat room is isolated for test users/staff.'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=(('OPEN', 'Open'), ('CLOSED', 'Closed')), default='OPEN')
    
    def __str__(self):
        client_name = self.client.username if self.client else "Unknown"
        return f"Chat with {client_name}"
    
    def save(self, *args, **kwargs):
        if not self.name and self.client:
            self.name = f"chat_{self.client.username}"
        if self.client:
            self.is_test_room = bool(self.client.is_test_user)
        elif self.queue:
            self.is_test_room = bool(self.queue.is_test_room)
        super().save(*args, **kwargs)
    
    class Meta:
        ordering = ['-created_at']


class Message(models.Model):
    """
    Message model for storing chat messages.
    """
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )
    content = models.TextField()
    attachment = models.FileField(upload_to='chat_attachments/', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    
    # Message Modification Fields
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_pinned = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.sender.username} in {self.room.name}: {self.content[:50]}"
    
    class Meta:
        ordering = ['timestamp']


class RoomParticipant(models.Model):
    """
    Track participants in each room.
    """
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name='participants'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='joined_rooms'
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['room', 'user']
        ordering = ['joined_at']
    
    def __str__(self):
        return f"{self.user.username} in {self.room.name}"
