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
    path('api/auth/', include('accounts.urls')),
    path('api/', include('chat.urls')),
    path('api/posts/', include('posts.urls')),
    path('api/blog/', include('blog.urls')),
    path('api/events/', include('events.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('admin/user-search/', admin_player_search_view),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
