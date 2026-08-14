from django.urls import path
from . import views


urlpatterns = [
    path('config/', views.config_view, name='plinko-config'),
    path('play/', views.play_view, name='plinko-play'),
    path('history/', views.history_view, name='plinko-history'),
    path('free-drop/config/', views.free_drop_config_view, name='plinko-free-drop-config'),
    path('free-drop/play/', views.free_drop_play_view, name='plinko-free-drop-play'),
]
