from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('csrf/', views.get_csrf_token, name='get_csrf_token'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('me/', views.current_user_view, name='current-user'),
]
