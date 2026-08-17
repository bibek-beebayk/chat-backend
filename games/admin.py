from django.contrib import admin
from django.utils.html import format_html
from .models import Game


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('thumbnail_preview', 'name', 'slug', 'is_active', 'updated_at')
    list_editable = ('is_active',)
    list_filter = ('is_active',)
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at', 'updated_at')

    def thumbnail_preview(self, obj):
        if not obj.thumbnail:
            return '—'
        return format_html('<img src="{}" style="width:40px;height:40px;object-fit:cover;border-radius:6px;" />', obj.thumbnail.url)
    thumbnail_preview.short_description = 'Thumbnail'
