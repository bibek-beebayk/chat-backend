from django.urls import path
from . import views


urlpatterns = [
    path('', views.game_list_view, name='games-list'),
    path('stats/', views.player_stats_view, name='games-player-stats'),
]
