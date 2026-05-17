from django.contrib import admin

from .models import Building, Unit


class UnitInline(admin.TabularInline):
    model = Unit
    extra = 0
    fields = ("label", "floor", "unit_type", "monthly_rent", "status")
    readonly_fields = ("status",)


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "total_floors", "paybill_number", "created_at")
    search_fields = ("name",)
    fieldsets = (
        (None, {"fields": ("name", "address", "total_floors", "notes")}),
        ("Statement header", {
            "fields": ("legal_name", "postal_address", "contact_phone", "contact_email"),
        }),
        ("Payment options (shown on rent statements)", {
            "fields": (
                "paybill_number", "paybill_account_format",
                "bank_name", "bank_branch", "bank_account", "bank_account_name",
            ),
        }),
    )
    inlines = [UnitInline]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("label", "building", "unit_type", "monthly_rent", "status")
    list_filter = ("status", "unit_type", "building")
    search_fields = ("label", "building__name")
    readonly_fields = ("status",)
