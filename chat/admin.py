from django.contrib import admin
from .models import Room, Message, RoomParticipant, SupportRoom


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['name', 'room_type', 'client', 'direct_player', 'direct_agent', 'current_handler', 'status', 'is_test_room', 'created_at']
    list_filter = ['room_type', 'status', 'is_test_room', 'created_at']
    search_fields = ['name', 'current_handler__username', 'client__username', 'direct_player__username', 'direct_agent__username']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'room', 'sender', 'content_preview', 'timestamp', 'is_read']
    list_filter = ['room', 'is_read', 'timestamp']
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
