from django.contrib import admin
from django.utils import timezone
from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'category',
        'audience',
        'priority',
        'is_pinned',
        'is_published',
        'published_at',
        'updated_at',
    )
    list_filter = ('category', 'audience', 'priority', 'is_pinned', 'is_published')
    search_fields = ('title', 'summary', 'content')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'published_at'
    actions = ('publish_announcements', 'unpublish_announcements', 'pin_announcements', 'unpin_announcements')
    fieldsets = (
        ('Content', {
            'fields': ('title', 'summary', 'content', 'cover_image'),
        }),
        ('Publishing', {
            'fields': ('category', 'audience', 'priority', 'is_pinned', 'is_published', 'published_at', 'created_by'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user
        if obj.is_published and obj.published_at is None:
            obj.published_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description='Publish selected announcements')
    def publish_announcements(self, request, queryset):
        queryset.update(is_published=True, published_at=timezone.now())

    @admin.action(description='Unpublish selected announcements')
    def unpublish_announcements(self, request, queryset):
        queryset.update(is_published=False)

    @admin.action(description='Pin selected announcements')
    def pin_announcements(self, request, queryset):
        queryset.update(is_pinned=True)

    @admin.action(description='Unpin selected announcements')
    def unpin_announcements(self, request, queryset):
        queryset.update(is_pinned=False)
