from django.urls import path
from . import views


urlpatterns = [
    path('home-stats/', views.home_stats_view, name='analytics-home-stats'),
    path('recent-activity/', views.recent_activity_view, name='analytics-recent-activity'),
    path('track/', views.track_view, name='analytics-track'),
    path('dashboard/', views.dashboard_view, name='analytics-dashboard'),
]
