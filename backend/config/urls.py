"""Root URL configuration."""
from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import HealthView


def _superadmin_only(request) -> bool:
    """Django's admin site has its own permission system, outside the access
    rules the API enforces, so only the superadmin may open it. Staff flags on
    other accounts no longer let them in."""
    user = request.user
    return bool(user.is_active and user.is_superuser)


admin.site.has_permission = _superadmin_only

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.buildings.urls")),
    path("api/", include("apps.tenants.urls")),
    path("api/", include("apps.payments.urls")),
    path("api/", include("apps.dashboard.urls")),
    path("api/", include("apps.expenses.urls")),
]
