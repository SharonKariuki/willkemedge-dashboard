from django.contrib import admin

from .models import Arrears, Payment, TenantNotification


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("tenant", "amount", "payment_date", "source", "period_month", "period_year")
    list_filter = ("source", "period_year", "period_month")
    search_fields = ("tenant__first_name", "tenant__last_name", "reference")
    readonly_fields = ("created_at",)


@admin.register(Arrears)
class ArrearsAdmin(admin.ModelAdmin):
    list_display = ("tenant", "period_month", "period_year", "expected_rent", "amount_paid", "balance", "is_cleared")
    list_filter = ("is_cleared", "period_year")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TenantNotification)
class TenantNotificationAdmin(admin.ModelAdmin):
    list_display = ("tenant", "channel", "status", "template_key", "sent_at", "created_at")
    list_filter = ("channel", "status", "template_key")
    search_fields = ("tenant__first_name", "tenant__last_name", "subject", "body")
    readonly_fields = ("created_at", "sent_at")
