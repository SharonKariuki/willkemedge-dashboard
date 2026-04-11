"""Tenant URL routes."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import TenantViewSet

router = DefaultRouter()
router.register("tenants", TenantViewSet, basename="tenant")

app_name = "tenants"

urlpatterns = [
    path("", include(router.urls)),
]
