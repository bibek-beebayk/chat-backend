from django.contrib import admin
from .models import Room, Message, RoomParticipant, SupportRoom, GroupJoinRequest


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'room_type', 'client', 'direct_player', 'direct_agent',
        'group_admin', 'current_handler', 'status', 'is_test_room', 'created_at'
    ]
    list_filter = ['room_type', 'status', 'is_test_room', 'created_at']
    search_fields = [
        'name', 'current_handler__username', 'client__username',
        'direct_player__username', 'direct_agent__username', 'group_admin__username'
    ]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'room', 'sender', 'content_preview', 'timestamp', 'is_read', 'is_broadcast']
    list_filter = ['room', 'is_read', 'is_broadcast', 'timestamp']
    search_fields = ['content', 'sender__username']
    ordering = ['-timestamp']

    def content_preview(self, obj):
        return obj.content[:50]
    content_preview.short_description = 'Content'


@admin.register(RoomParticipant)
class RoomParticipantAdmin(admin.ModelAdmin):
    list_display = ['room', 'user', 'joined_at', 'is_active']
    list_filter = ['is_active', 'joined_at']
    search_fields = ['room__name', 'user__username']


@admin.register(SupportRoom)
class SupportRoomAdmin(admin.ModelAdmin):
    list_display = ['name', 'staff', 'is_active', 'is_test_room']
    list_filter = ['is_active', 'is_test_room']
    search_fields = ['name', 'staff__username']


@admin.register(GroupJoinRequest)
class GroupJoinRequestAdmin(admin.ModelAdmin):
    list_display = ['room', 'player', 'status', 'requested_at', 'reviewed_at', 'reviewed_by']
    list_filter = ['status', 'requested_at', 'reviewed_at']
    search_fields = ['room__name', 'player__username', 'reviewed_by__username']
