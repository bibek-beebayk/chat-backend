from django.urls import path
from . import views


urlpatterns = [
    path('streak/', views.streak_status_view, name='login-streak-status'),
    path('streak/visit/', views.record_streak_visit_view, name='login-streak-visit'),
    path('streak/redeem/', views.create_redemption_request_view, name='login-streak-redeem'),
    path('streak/redemptions/', views.redemption_request_list_view, name='login-streak-redemptions'),
    path('streak/redemptions/<int:request_id>/', views.redemption_request_update_view, name='login-streak-redemption-update'),
    path('scratch-redemptions/', views.create_scratch_redemption_view, name='scratch-redemption-create'),
]
