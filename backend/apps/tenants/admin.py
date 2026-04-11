from django.contrib import admin

from .models import Tenant, TenantDocument


class DocumentInline(admin.TabularInline):
    model = TenantDocument
    extra = 0
    readonly_fields = ("uploaded_at",)


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("full_name", "id_number", "unit", "status", "move_in_date", "move_out_date")
    list_filter = ("status", "unit__building")
    search_fields = ("first_name", "last_name", "id_number", "phone")
    inlines = [DocumentInline]
