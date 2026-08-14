from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .views import PushTokenViewSet

router = DefaultRouter()
router.register(r'devices', PushTokenViewSet, basename='push-device')

urlpatterns = [
    path('list/', views.notification_list_view, name='notification-list'),
    path('<int:notification_id>/read/', views.notification_mark_read_view, name='notification-mark-read'),
    path('read-all/', views.notification_mark_all_read_view, name='notification-mark-all-read'),
    path('', include(router.urls)),
]
