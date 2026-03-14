from django.urls import path
from . import views


urlpatterns = [
    path('feed/', views.blog_feed_view, name='blog-feed'),
    path('<int:pk>/', views.blog_detail_view, name='blog-detail'),
    path('slug/<slug:slug>/', views.blog_detail_by_slug_view, name='blog-detail-slug'),
]

