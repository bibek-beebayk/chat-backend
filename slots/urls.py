from django.urls import path
from . import views

urlpatterns = [
    path('config/', views.config_view, name='slots-config'),
    path('play/', views.play_view, name='slots-play'),
    path('history/', views.history_view, name='slots-history'),
]
