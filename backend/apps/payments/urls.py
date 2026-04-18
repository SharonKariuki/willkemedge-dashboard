"""Payment URL routes — includes M-Pesa and bank webhook endpoints."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .bank import BankWebhookView
from .notification_views import NotificationViewSet
from .views import ArrearsViewSet, PaymentViewSet
from .views_mpesa import MpesaConfirmView, MpesaValidateView

router = DefaultRouter()
router.register("payments", PaymentViewSet, basename="payment")
router.register("arrears", ArrearsViewSet, basename="arrears")
router.register("notifications", NotificationViewSet, basename="notification")

app_name = "payments"

urlpatterns = [
    path("", include(router.urls)),
    path("payments/mpesa/validate/", MpesaValidateView.as_view(), name="mpesa-validate"),
    path("payments/mpesa/confirm/",   MpesaConfirmView.as_view(),  name="mpesa-confirm"),
    path("payments/bank/webhook/",    BankWebhookView.as_view(),   name="bank-webhook"),
]
