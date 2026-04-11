from django.contrib import admin

from .models import Arrears, Payment


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
