from django.urls import path
from . import views


urlpatterns = [
    path('balance/', views.balance_view, name='points-balance'),
    path('ledger/', views.ledger_view, name='points-ledger'),
    path('redeem/', views.create_redemption_view, name='points-redeem'),
    path('redemptions/', views.redemption_list_view, name='points-redemptions'),
    path('redemptions/<int:request_id>/', views.redemption_update_view, name='points-redemption-update'),
    path('actions/', views.action_list_view, name='points-actions'),
    path('award/', views.award_points_view, name='points-award'),
]
