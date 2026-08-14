from django.urls import path
from . import views

urlpatterns = [
    path('status/', views.status_view, name='xp-status'),
    path('actions/', views.action_list_view, name='xp-actions'),
]
