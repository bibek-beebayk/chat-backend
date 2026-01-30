from django.urls import path
from . import views

urlpatterns = [
    path('latest/', views.get_latest_event, name='get_latest_event'),
    path('active/', views.get_active_events, name='get_active_events'),

    path('register-init/', views.register_init_view, name='register_init'),
    path('register/', views.register_for_event_view, name='register_for_event'),
    path('check-eligibility/', views.check_eligibility_view, name='check_eligibility'),
    path('set-password/', views.set_password_view, name='set_password'),
    path('verify-otp/', views.verify_event_otp_view, name='verify_event_otp'),
]
