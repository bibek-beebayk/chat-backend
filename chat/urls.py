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
    path('rooms/<int:room_id>/attachments/', views.upload_attachment_view, name='upload-attachment'),
    path('messages/<int:message_id>/edit/', views.edit_message, name='edit-message'),
    path('messages/<int:message_id>/delete/', views.delete_message, name='delete-message'),
    path('messages/<int:message_id>/pin/', views.pin_message, name='pin-message'),
    path('staff/dashboard/', views.staff_dashboard_view, name='staff-dashboard'),
] + router.urls
