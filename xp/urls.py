from django.urls import path
from . import views

urlpatterns = [
    path('status/', views.status_view, name='xp-status'),
    path('acknowledge-level-up/', views.acknowledge_level_up_view, name='xp-acknowledge-level-up'),
    path('daily-progress/', views.daily_progress_view, name='xp-daily-progress'),
    path('achievements/', views.achievements_view, name='xp-achievements'),
    path('rank-tiers/', views.rank_tiers_view, name='xp-rank-tiers'),
    path('actions/', views.action_list_view, name='xp-actions'),
]
