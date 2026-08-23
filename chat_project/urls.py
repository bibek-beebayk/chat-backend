"""
URL configuration for chat_project project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts.admin import player_search_view as admin_player_search_view
from analytics.admin import dashboard_view

urlpatterns = [
    path('admin/', dashboard_view), # Override default admin index
    path('admin/', admin.site.urls), # Standard handling for other paths
    path('ckeditor/', include('ckeditor_uploader.urls')),
    path('api/auth/', include('accounts.urls')),
    path('api/social/', include('social.urls')),
    path('api/', include('chat.urls')),
    path('api/posts/', include('posts.urls')),
    path('api/blog/', include('blog.urls')),
    path('api/events/', include('events.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/analytics/', include('analytics.urls')),
    path('api/announcements/', include('announcements.urls')),
    path('api/faqs/', include('faqs.urls')),
    path('api/rewards/', include('rewards.urls')),
    path('api/points/', include('points.urls')),
    path('api/xp/', include('xp.urls')),
    path('api/games/', include('games.urls')),
    path('api/plinko/', include('plinko.urls')),
    path('api/slots/', include('slots.urls')),
    path('api/rocket/', include('rocket.urls')),
    path('api/stories/', include('stories.urls')),
    path('admin/user-search/', admin_player_search_view),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
