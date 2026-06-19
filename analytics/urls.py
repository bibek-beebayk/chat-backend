from django.urls import path
from . import views


urlpatterns = [
    path('home-stats/', views.home_stats_view, name='analytics-home-stats'),
    path('recent-activity/', views.recent_activity_view, name='analytics-recent-activity'),
]
