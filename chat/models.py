from django.db import models
from django.conf import settings
from django.db.models import Q


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
    ROOM_TYPE_CHOICES = (
        ('support', 'Support'),
        ('direct_agent', 'Direct Agent'),
    )

    name = models.CharField(max_length=100, blank=True)
    room_type = models.CharField(max_length=20, choices=ROOM_TYPE_CHOICES, default='support')
    client = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='support_room',
        limit_choices_to={'user_type__in': ['player', 'agent']},
        null=True,
        blank=True
    )
    direct_player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='direct_agent_rooms',
        limit_choices_to={'user_type': 'player'},
        null=True,
        blank=True,
    )
    direct_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='direct_player_rooms',
        limit_choices_to={'user_type': 'agent'},
        null=True,
        blank=True,
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
        if self.room_type == 'direct_agent':
            p = self.direct_player.username if self.direct_player else "Unknown player"
            a = self.direct_agent.username if self.direct_agent else "Unknown agent"
            return f"Direct chat {p} ↔ {a}"
        client_name = self.client.username if self.client else "Unknown"
        return f"Support chat with {client_name}"
    
    def save(self, *args, **kwargs):
        if self.room_type == 'direct_agent':
            if not self.name and self.direct_player and self.direct_agent:
                self.name = f"direct_{self.direct_player.username}_{self.direct_agent.username}"
            if self.direct_player:
                self.is_test_room = bool(self.direct_player.is_test_user)
            elif self.direct_agent:
                self.is_test_room = bool(self.direct_agent.is_test_user)
            self.client = None
            self.queue = None
            self.current_handler = None
        else:
            if not self.name and self.client:
                self.name = f"chat_{self.client.username}"
            if self.client:
                self.is_test_room = bool(self.client.is_test_user)
            elif self.queue:
                self.is_test_room = bool(self.queue.is_test_room)
        super().save(*args, **kwargs)
    
    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['direct_player', 'direct_agent'],
                condition=Q(room_type='direct_agent'),
                name='unique_player_agent_direct_room',
            ),
        ]


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
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies',
    )
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
