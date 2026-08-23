from django.urls import path
from . import views

urlpatterns = [
    path('status/', views.status_view, name='xp-status'),
    path('daily-progress/', views.daily_progress_view, name='xp-daily-progress'),
    path('achievements/', views.achievements_view, name='xp-achievements'),
    path('actions/', views.action_list_view, name='xp-actions'),
]
