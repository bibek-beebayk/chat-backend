from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('me/', views.current_user_view, name='current-user'),
    path('csrf/', views.get_csrf_token, name='csrf-token'),
    path('change-password/', views.change_password_view, name='change-password'),
    path('verify-otp/', views.verify_otp_view, name='verify-otp'),
    path('resend-otp/', views.resend_otp_view, name='resend-otp'),
    path('initiate-verification-request/', views.initiate_verification_request_view, name='initiate-verification-request'),
    path('verify-user-id/', views.verify_user_id_view, name='verify-user-id'),
    path('test-email/', views.test_email_view, name='test-email'),
]
