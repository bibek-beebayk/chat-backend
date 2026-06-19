from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import FAQViewSet


router = DefaultRouter()
router.register(r'', FAQViewSet, basename='faq')

urlpatterns = [
    path('', include(router.urls)),
]
