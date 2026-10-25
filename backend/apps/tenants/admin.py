from django.contrib import admin

from .models import Tenant, TenantDocument


class DocumentInline(admin.TabularInline):
    """KYC documents, read-only. Uploads go through the tenant page, which
    stores them in the database; an admin upload would write to the
    deploy-wiped disk instead."""

    model = TenantDocument
    extra = 0
    fields = ("doc_type", "original_name", "content_type", "size", "uploaded_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("full_name", "id_number", "unit", "status", "move_in_date", "move_out_date")
    list_filter = ("status", "unit__building")
    search_fields = ("first_name", "last_name", "id_number", "phone")
    inlines = [DocumentInline]
