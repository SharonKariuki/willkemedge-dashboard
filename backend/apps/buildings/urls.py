"""Building and Unit URL routes."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BuildingViewSet, UnitViewSet

router = DefaultRouter()
router.register("buildings", BuildingViewSet, basename="building")
router.register("units", UnitViewSet, basename="unit")

app_name = "buildings"

urlpatterns = [
    path("", include(router.urls)),
]
