from django.urls import path
from . import views

from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'support-rooms', views.SupportRoomViewSet)

urlpatterns = [
    # Agent flow removed - views still exist in chat/views.py, just unexposed.
    # path('agents/search/', views.agent_search_view, name='agent-search'),
    path('groups/discover/', views.discover_groups_view, name='groups-discover'),
    # path('groups/', views.create_group_view, name='groups-create'),
    # path('groups/<int:room_id>/', views.delete_group_view, name='groups-delete'),
    # path('groups/managed/requests/', views.managed_group_join_requests_view, name='groups-managed-requests'),
    # path('groups/join-requests/<int:request_id>/review/', views.review_group_join_request_view, name='groups-join-request-review'),
    path('groups/<int:room_id>/join-requests/', views.request_group_join_view, name='groups-join-request-create'),
    path('groups/<int:room_id>/leave/', views.leave_group_view, name='groups-leave'),
    path('groups/<int:room_id>/members/', views.group_members_view, name='groups-members'),
    path('groups/<int:room_id>/broadcast/', views.group_broadcast_view, name='groups-broadcast'),
    path('groups/<int:room_id>/direct/<int:player_id>/start/', views.start_direct_chat_from_group_view, name='groups-direct-start'),
    path('rooms/', views.room_list_view, name='room-list'),
    path('rooms/message-requests/', views.room_message_requests_view, name='room-message-requests'),
    # path('rooms/direct/start/', views.start_direct_agent_chat_view, name='direct-agent-chat-start'),
    path('rooms/direct/player/start/', views.start_direct_player_chat_view, name='direct-player-chat-start'),
    path('rooms/<int:room_id>/', views.room_detail_view, name='room-detail'),
    path('rooms/<int:room_id>/messages/', views.room_messages_view, name='room-messages'),
    path('rooms/<int:room_id>/request/respond/', views.room_message_request_respond_view, name='room-message-request-respond'),
    path('rooms/<int:room_id>/join/', views.join_room_view, name='join-room'),
    path('rooms/<int:room_id>/pinned/', views.pinned_messages_view, name='room-pinned-messages'),
    path('rooms/<int:room_id>/close/', views.close_room_view, name='close-room'),
    path('rooms/<int:room_id>/internal-note/', views.room_internal_note_view, name='room-internal-note'),
    path('rooms/<int:room_id>/attachments/', views.upload_attachment_view, name='upload-attachment'),
    path('quick-replies/', views.quick_replies_view, name='quick-replies'),
    path('quick-replies/<int:reply_id>/', views.quick_reply_detail_view, name='quick-reply-detail'),
    path('messages/<int:message_id>/edit/', views.edit_message, name='edit-message'),
    path('messages/<int:message_id>/delete/', views.delete_message, name='delete-message'),
    path('messages/<int:message_id>/pin/', views.pin_message, name='pin-message'),
    path('staff/dashboard/', views.staff_dashboard_view, name='staff-dashboard'),
    path('rooms/switch-station/', views.switch_station_view, name='switch-station'),
] + router.urls
