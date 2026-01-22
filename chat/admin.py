from django.contrib import admin
from .models import Room, Message, RoomParticipant, SupportRoom


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['name', 'staff_assigned', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'staff_assigned__username']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'room', 'sender', 'content_preview', 'timestamp', 'is_read']
    list_filter = ['room', 'is_read', 'timestamp']
    search_fields = ['content', 'sender__username']
    
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
    list_display = ['name', 'staff', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'staff__username']
