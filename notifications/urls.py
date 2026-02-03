from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PushTokenViewSet

router = DefaultRouter()
router.register(r'devices', PushTokenViewSet, basename='push-device')

urlpatterns = [
    path('', include(router.urls)),
]
