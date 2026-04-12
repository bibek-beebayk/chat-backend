from django.urls import path
from . import views

from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.CustomTokenObtainPairView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', views.logout_view, name='logout'),
    path('me/', views.current_user_view, name='current-user'),
    path('profile/picture/', views.update_profile_picture_view, name='update-profile-picture'),
    path('email-change/request/', views.request_email_change_view, name='request-email-change'),
    path('email-change/verify/', views.verify_email_change_view, name='verify-email-change'),
    path('home-info/', views.home_info_view, name='home-info'),
    path('change-password/', views.change_password_view, name='change-password'),
    path('verify-current-password/', views.verify_current_password_view, name='verify-current-password'),
    path('delete-account/', views.delete_account_view, name='delete-account'),
    path('verify-otp/', views.verify_otp_view, name='verify-otp'),
    path('resend-otp/', views.resend_otp_view, name='resend-otp'),
    path('initiate-verification-request/', views.initiate_verification_request_view, name='initiate-verification-request'),
    path('verify-user-id/', views.verify_user_id_view, name='verify-user-id'),
    path('test-email/', views.test_email_view, name='test-email'),
    path('forgot-password/initiate/', views.initiate_password_reset_view, name='forgot-password-initiate'),
    path('forgot-password/verify-otp/', views.verify_reset_otp_view, name='forgot-password-verify-otp'),
    path('forgot-password/complete/', views.reset_password_complete_view, name='forgot-password-complete'),
    path('app-version/', views.latest_app_version_view, name='app-version'),
]
