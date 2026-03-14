from django.contrib import admin
from .models import Blog


@admin.register(Blog)
class BlogAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'author', 'is_published', 'published_at', 'created_at')
    list_filter = ('is_published', 'published_at', 'created_at')
    search_fields = ('title', 'slug', 'excerpt', 'meta_title', 'meta_description', 'content')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('created_at', 'updated_at')
