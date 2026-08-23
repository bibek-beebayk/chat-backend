from django.contrib import admin
from .models import Story, StoryView


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'author', 'created_at', 'expires_at')
    list_filter = ('created_at',)
    search_fields = ('author__username', 'author__email', 'caption')
    readonly_fields = ('created_at', 'expires_at')


@admin.register(StoryView)
class StoryViewAdmin(admin.ModelAdmin):
    list_display = ('story', 'viewer', 'viewed_at')
    search_fields = ('story__author__username', 'viewer__username')
    readonly_fields = ('viewed_at',)
