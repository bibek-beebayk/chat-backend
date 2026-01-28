from django.urls import path
from . import views

urlpatterns = [
    path('latest/', views.get_latest_event, name='get_latest_event'),

    path('register-init/', views.register_init_view, name='register_init'),
    path('set-password/', views.set_password_view, name='set_password'),
    path('verify-otp/', views.verify_event_otp_view, name='verify_event_otp'),
]
