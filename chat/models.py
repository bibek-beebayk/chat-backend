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
        ('group', 'Group'),
    )
    DIRECT_REQUEST_STATUS_CHOICES = (
        ('accepted', 'Accepted'),
        ('pending', 'Pending'),
        ('rejected', 'Rejected'),
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
        null=True,
        blank=True,
    )
    direct_request_status = models.CharField(
        max_length=10,
        choices=DIRECT_REQUEST_STATUS_CHOICES,
        default='accepted',
    )
    direct_request_initiator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='initiated_direct_requests',
    )
    group_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='managed_group_rooms',
        limit_choices_to={'user_type': 'agent'},
        null=True,
        blank=True,
    )
    group_description = models.CharField(max_length=240, blank=True)
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
    resolution_reason = models.CharField(max_length=240, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_rooms',
    )

    def __str__(self):
        if self.room_type == 'direct_agent':
            p = self.direct_player.username if self.direct_player else "Unknown player"
            a = self.direct_agent.username if self.direct_agent else "Unknown peer"
            return f"Direct chat {p} <-> {a}"
        if self.room_type == 'group':
            admin_name = self.group_admin.username if self.group_admin else "Unknown admin"
            return f"Group {self.name or self.id} (admin: {admin_name})"
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
            self.group_admin = None
            self.group_description = ''
        elif self.room_type == 'group':
            if self.group_admin:
                self.is_test_room = bool(self.group_admin.is_test_user)
            self.client = None
            self.queue = None
            self.current_handler = None
            self.direct_player = None
            self.direct_agent = None
            self.direct_request_status = 'accepted'
            self.direct_request_initiator = None
        else:
            if not self.name and self.client:
                self.name = f"chat_{self.client.username}"
            if self.client:
                self.is_test_room = bool(self.client.is_test_user)
            elif self.queue:
                self.is_test_room = bool(self.queue.is_test_room)
            self.direct_player = None
            self.direct_agent = None
            self.group_admin = None
            self.group_description = ''
            self.direct_request_status = 'accepted'
            self.direct_request_initiator = None
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
    is_broadcast = models.BooleanField(default=False)

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


class AgentQuickReply(models.Model):
    """
    Saved quick replies for agents/staff to respond faster.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='agent_quick_replies',
    )
    title = models.CharField(max_length=80)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title', '-updated_at']
        unique_together = ('user', 'title')

    def __str__(self):
        return f"{self.user.username}: {self.title}"


class ChatInternalNote(models.Model):
    """
    Private chat note for agent/staff collaboration.
    Not shown to players/agents on client side unless authorized.
    """
    room = models.OneToOneField(
        Room,
        on_delete=models.CASCADE,
        related_name='internal_note',
    )
    content = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_notes_updated',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Internal note for room {self.room_id}"


class GroupJoinRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name='join_requests',
        limit_choices_to={'room_type': 'group'},
    )
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='group_join_requests',
        limit_choices_to={'user_type': 'player'},
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_group_join_requests',
        limit_choices_to={'user_type': 'agent'},
    )

    class Meta:
        ordering = ['-requested_at']
        constraints = [
            models.UniqueConstraint(
                fields=['room', 'player'],
                condition=Q(status='pending'),
                name='unique_pending_group_join_request',
            ),
        ]

    def __str__(self):
        return f"{self.player.username} -> group {self.room_id} ({self.status})"
