from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, LoginAttempt, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("email", "username", "role", "is_staff", "is_active", "date_joined")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    ordering = ("email",)
    fieldsets = UserAdmin.fieldsets + (("Dashboard role", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Dashboard role", {"fields": ("role",)}),)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only by design — the audit trail is append-only.

    Nothing in the codebase updates or deletes a row; blocking it here means the
    log cannot be quietly tidied up from the admin either.
    """

    list_display = ("created_at", "kind", "action", "object_label", "actor_label", "source", "summary")
    list_filter = ("kind", "source", "is_financial", "object_type")
    search_fields = ("summary", "object_label", "actor_label", "actor__email", "session_id", "request_id")
    date_hierarchy = "created_at"
    readonly_fields = tuple(f.name for f in AuditLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("email", "ip_address", "successful", "attempted_at")
    list_filter = ("successful", "attempted_at")
    search_fields = ("email", "ip_address")
    readonly_fields = ("email", "ip_address", "user_agent", "successful", "attempted_at")
