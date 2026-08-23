from django.urls import path

from . import views

urlpatterns = [
    path('', views.story_list_view, name='story-list'),
    path('<int:story_id>/view/', views.story_mark_viewed_view, name='story-mark-viewed'),
    path('<int:story_id>/', views.story_delete_view, name='story-delete'),
]
