"""Payment URL routes — includes M-Pesa and bank webhook endpoints."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .coop_ipn import CoopIpnView
from .notification_views import NotificationViewSet
from .reconciliation_views import DailyReconciliationTriggerView
from .views import ArrearsViewSet, PaymentViewSet, TransactionViewSet

router = DefaultRouter()
router.register("payments", PaymentViewSet, basename="payment")
router.register("arrears", ArrearsViewSet, basename="arrears")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("transactions", TransactionViewSet, basename="transaction")

app_name = "payments"

urlpatterns = [
    path("", include(router.urls)),
    path("payments/coop/ipn/", CoopIpnView.as_view(), name="coop-ipn"),
    path("payments/coop/reconcile-daily/", DailyReconciliationTriggerView.as_view(), name="coop-reconcile-daily"),
]
