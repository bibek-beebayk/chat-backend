from django.urls import path
from . import views

from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'support-rooms', views.SupportRoomViewSet)

urlpatterns = [
    path('rooms/', views.room_list_view, name='room-list'),
    path('rooms/<int:room_id>/', views.room_detail_view, name='room-detail'),
    path('rooms/<int:room_id>/messages/', views.room_messages_view, name='room-messages'),
    path('rooms/<int:room_id>/join/', views.join_room_view, name='join-room'),
    path('rooms/<int:room_id>/close/', views.close_room_view, name='close-room'),
    path('staff/dashboard/', views.staff_dashboard_view, name='staff-dashboard'),
] + router.urls
