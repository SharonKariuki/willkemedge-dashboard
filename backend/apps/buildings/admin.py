from django.contrib import admin

from .models import Building, Unit, UnitAlias


class UnitInline(admin.TabularInline):
    model = Unit
    extra = 0
    fields = ("label", "floor", "unit_type", "monthly_rent", "status")
    readonly_fields = ("status",)


class UnitAliasInline(admin.TabularInline):
    model = UnitAlias
    extra = 0
    fields = ("label", "note", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "total_floors", "paybill_number", "created_at")
    search_fields = ("name",)
    fieldsets = (
        (None, {"fields": ("name", "code", "address", "total_floors", "notes")}),
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
    inlines = [UnitAliasInline]


@admin.register(UnitAlias)
class UnitAliasAdmin(admin.ModelAdmin):
    list_display = ("label", "unit", "note", "created_at")
    search_fields = ("label", "unit__label", "unit__building__name")
