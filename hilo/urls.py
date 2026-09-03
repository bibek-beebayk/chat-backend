from django.urls import path
from . import views

urlpatterns = [
    path('config/', views.config_view, name='hilo-config'),
    path('play/', views.play_view, name='hilo-play'),
    path('current/', views.current_round_view, name='hilo-current'),
    path('predict/', views.predict_view, name='hilo-predict'),
    path('cashout/', views.cashout_view, name='hilo-cashout'),
    path('history/', views.history_view, name='hilo-history'),
    path('stats/', views.stats_view, name='hilo-stats'),
]
