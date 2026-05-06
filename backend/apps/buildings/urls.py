"""Building, Unit and Maintenance URL routes."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BuildingViewSet, MaintenanceRequestViewSet, UnitViewSet

router = DefaultRouter()
router.register("buildings", BuildingViewSet, basename="building")
router.register("units", UnitViewSet, basename="unit")
router.register("maintenance", MaintenanceRequestViewSet, basename="maintenance")

app_name = "buildings"

urlpatterns = [
    path("", include(router.urls)),
]
