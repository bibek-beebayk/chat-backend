from django.urls import path
from . import views

urlpatterns = [
    path('config/', views.config_view, name='rocket-config'),
    path('play/', views.play_view, name='rocket-play'),
    path('current/', views.current_round_view, name='rocket-current'),
    path('cashout/', views.cashout_view, name='rocket-cashout'),
    path('history/', views.history_view, name='rocket-history'),
]
