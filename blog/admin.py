from django.contrib import admin
from .models import Blog, BlogComment, BlogReaction


@admin.register(Blog)
class BlogAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'author', 'is_published', 'published_at', 'created_at')
    list_filter = ('is_published', 'published_at', 'created_at')
    search_fields = ('title', 'slug', 'excerpt', 'meta_title', 'meta_description', 'content')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('created_at', 'updated_at')


@admin.register(BlogComment)
class BlogCommentAdmin(admin.ModelAdmin):
    list_display = ('blog', 'display_name', 'created_at', 'is_hidden')
    list_filter = ('is_hidden', 'created_at')
    search_fields = ('display_name', 'content', 'blog__title')
    readonly_fields = ('created_at', 'updated_at', 'visitor_hash')


@admin.register(BlogReaction)
class BlogReactionAdmin(admin.ModelAdmin):
    list_display = ('blog', 'reaction_type', 'created_at')
    list_filter = ('reaction_type', 'created_at')
    search_fields = ('blog__title',)
    readonly_fields = ('created_at', 'updated_at', 'visitor_hash')
