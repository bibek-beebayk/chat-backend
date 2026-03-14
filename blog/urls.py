from django.urls import path
from . import views


urlpatterns = [
    path('feed/', views.blog_feed_view, name='blog-feed'),
    path('<int:pk>/', views.blog_detail_view, name='blog-detail'),
    path('slug/<slug:slug>/', views.blog_detail_by_slug_view, name='blog-detail-slug'),
    path('slug/<slug:slug>/interactions/', views.blog_interactions_view, name='blog-interactions'),
    path('slug/<slug:slug>/react/', views.blog_react_view, name='blog-react'),
    path('slug/<slug:slug>/comments/', views.blog_comment_create_view, name='blog-comment-create'),
    path('comments/<int:comment_id>/', views.blog_comment_delete_view, name='blog-comment-delete'),
]

