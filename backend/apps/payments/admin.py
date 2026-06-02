"""
Django Admin for the payments app.

CoopIpnEventAdmin provides two one-click actions:
  • authorize_reversal  — Dr. Osoro approves a REVERSAL_PENDING event; the
                          linked Payment (if found) is voided via a compensating
                          entry and the event is marked RECORDED → reversed.
  • assign_to_tenant    — assign an UNMATCHED credit to a chosen tenant and
                          run the arrears-first allocator, then send the receipt.

Both are registered as Django admin actions on the model's changelist.
"""
from django import forms
from django.contrib import admin, messages
from django.db import transaction as db_transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Arrears,
    CoopIpnEvent,
    CoopIpnStatus,
    Payment,
    TenantNotification,
    UtilityCharge,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _void_payment(payment: Payment, notes: str = "") -> Payment:
    """Create an equal-and-opposite Payment to void an existing one.

    We never mutate the original (immutable financial records). The
    compensating entry has a negative amount and references the original.
    """
    return Payment.objects.create(
        tenant=payment.tenant,
        amount=-payment.amount,
        payment_date=payment.payment_date,
        period_month=payment.period_month,
        period_year=payment.period_year,
        source=payment.source,
        reference=f"VOID:{payment.reference or payment.pk}",
        notes=notes or f"Reversal authorized; voids payment #{payment.pk}",
    )


# ---------------------------------------------------------------------------
# Assign-to-tenant form (for the intermediate admin page)
# ---------------------------------------------------------------------------

class AssignTenantForm(forms.Form):
    """Lets the admin pick a tenant to assign an UNMATCHED IPN credit to."""
    from apps.tenants.models import Tenant, TenantStatus  # local import avoids circular

    tenant = forms.ModelChoiceField(
        queryset=None,  # set in __init__
        label="Assign to tenant",
        help_text="Select the tenant this credit belongs to.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.tenants.models import Tenant, TenantStatus
        self.fields["tenant"].queryset = (
            Tenant.objects.select_related("unit", "unit__building")
            .filter(status=TenantStatus.ACTIVE)
            .order_by("unit__building__name", "unit__label")
        )


# ---------------------------------------------------------------------------
# Payment admin
# ---------------------------------------------------------------------------

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "tenant", "amount", "payment_type", "payment_date",
        "source", "period_month", "period_year",
    )
    list_filter = ("payment_type", "source", "period_year", "period_month")
    search_fields = ("tenant__first_name", "tenant__last_name", "reference")
    readonly_fields = ("created_at",)


@admin.register(Arrears)
class ArrearsAdmin(admin.ModelAdmin):
    list_display = (
        "tenant", "period_month", "period_year",
        "expected_rent", "amount_paid", "balance", "is_cleared",
    )
    list_filter = ("is_cleared", "period_year")
    readonly_fields = ("created_at", "updated_at")


@admin.register(UtilityCharge)
class UtilityChargeAdmin(admin.ModelAdmin):
    list_display = (
        "tenant", "label", "posting_date",
        "period_month", "period_year", "units", "amount",
    )
    list_filter = ("label", "period_year", "period_month")
    search_fields = ("tenant__first_name", "tenant__last_name", "notes")
    readonly_fields = ("created_at",)


# ---------------------------------------------------------------------------
# Co-op IPN event admin — review queue + one-click actions
# ---------------------------------------------------------------------------

@admin.register(CoopIpnEvent)
class CoopIpnEventAdmin(admin.ModelAdmin):
    """
    Review queue for Co-op IPN credits.

    Useful filters:
      • status = Unmatched     → credits to assign to a tenant
      • status = Reversal …    → reversals awaiting director authorization
    """
    list_display = (
        "transaction_id", "amount", "channel", "event_type",
        "status_badge", "payment_link", "received_at",
    )
    list_filter = ("status", "channel", "event_type")
    search_fields = ("transaction_id", "payment_ref", "account_number", "narration")
    readonly_fields = (
        "transaction_id", "payment_ref", "account_number", "amount",
        "event_type", "channel", "narration", "raw_payload",
        "payment", "received_at",
    )
    date_hierarchy = "received_at"
    actions = ["authorize_reversal_action", "assign_to_tenant_action"]

    # ── custom URL for the assign-tenant intermediate page ───────────────

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path(
                "<int:event_id>/assign-tenant/",
                self.admin_site.admin_view(self.assign_tenant_view),
                name="payments_coopipnevent_assign_tenant",
            ),
        ]
        return extra + urls

    # ── display helpers ──────────────────────────────────────────────────

    @admin.display(description="Status")
    def status_badge(self, obj):
        colours = {
            CoopIpnStatus.RECORDED: "#16a34a",
            CoopIpnStatus.UNMATCHED: "#d97706",
            CoopIpnStatus.REVERSAL_PENDING: "#dc2626",
            CoopIpnStatus.ERROR: "#dc2626",
            CoopIpnStatus.IGNORED: "#6b7280",
            CoopIpnStatus.DUPLICATE: "#6b7280",
        }
        colour = colours.get(obj.status, "#374151")
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description="Payment")
    def payment_link(self, obj):
        if not obj.payment_id:
            return "—"
        url = reverse("admin:payments_payment_change", args=[obj.payment_id])
        return format_html('<a href="{}">{}</a>', url, f"#{obj.payment_id}")

    # ── action: authorize reversal ────────────────────────────────────────

    @admin.action(description="✅  Authorize selected reversal(s) — voids linked payment(s)")
    def authorize_reversal_action(self, request, queryset):
        # Maker-checker: only the authorising director may authorize a reversal.
        # If DIRECTOR_EMAIL is set, gate on it; otherwise fall back to superuser.
        from django.conf import settings as dj_settings
        director_email = (getattr(dj_settings, "DIRECTOR_EMAIL", "") or "").strip().lower()
        user_email = (request.user.email or "").strip().lower()
        if director_email:
            if user_email != director_email:
                self.message_user(
                    request,
                    "Only the authorising director may authorize bank reversals.",
                    level=messages.ERROR,
                )
                return
        elif not request.user.is_superuser:
            self.message_user(
                request,
                "Only a superuser (or the configured director) may authorize reversals.",
                level=messages.ERROR,
            )
            return

        pending_ids = list(
            queryset.filter(status=CoopIpnStatus.REVERSAL_PENDING).values_list("pk", flat=True)
        )
        if not pending_ids:
            self.message_user(
                request,
                "No events with status 'Reversal — awaiting authorization' in selection.",
                level=messages.WARNING,
            )
            return

        voided = 0
        skipped = 0
        for event_id in pending_ids:
            try:
                with db_transaction.atomic():
                    # Lock the row and re-check status under the lock so a
                    # concurrent click can't double-void.
                    event = (
                        CoopIpnEvent.objects.select_for_update()
                        .get(pk=event_id)
                    )
                    if event.status != CoopIpnStatus.REVERSAL_PENDING:
                        skipped += 1
                        continue
                    if event.payment_id:
                        _void_payment(
                            event.payment,
                            notes=f"Authorized reversal by {request.user}; "
                                  f"IPN event #{event.pk} ({event.transaction_id})",
                        )
                        p = event.payment
                        from .services import _update_arrears
                        _update_arrears(p.tenant, p.period_month, p.period_year)
                        voided += 1
                    event.status = CoopIpnStatus.REVERSAL_APPLIED
                    event.detail = f"{event.detail}; authorized by {request.user}"
                    event.authorized_by = request.user
                    event.authorized_at = timezone.now()
                    event.save(update_fields=[
                        "status", "detail", "authorized_by", "authorized_at",
                    ])
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                self.message_user(
                    request,
                    f"Error processing event #{event_id}: {exc}",
                    level=messages.ERROR,
                )

        if voided:
            self.message_user(
                request,
                f"{voided} reversal(s) authorized; compensating payment(s) created.",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"{skipped} event(s) skipped due to errors (see above).",
                level=messages.WARNING,
            )

    # ── action: assign unmatched → tenant ─────────────────────────────────

    @admin.action(description="👤  Assign selected unmatched credit(s) to a tenant…")
    def assign_to_tenant_action(self, request, queryset):
        """
        For multi-select: if exactly one event is selected, go to the
        intermediate form. If multiple are selected, require single selection.
        """
        unmatched = queryset.filter(status=CoopIpnStatus.UNMATCHED)
        if unmatched.count() == 0:
            self.message_user(
                request,
                "Select at least one Unmatched event to assign.",
                level=messages.WARNING,
            )
            return
        if unmatched.count() > 1:
            self.message_user(
                request,
                "Please select exactly one unmatched event at a time to assign.",
                level=messages.WARNING,
            )
            return
        event = unmatched.first()
        url = reverse("admin:payments_coopipnevent_assign_tenant", args=[event.pk])
        return HttpResponseRedirect(url)

    def assign_tenant_view(self, request, event_id):
        """Intermediate admin page to pick a tenant for an unmatched IPN credit."""

        from .services import allocate_payment_fifo
        from .tasks import send_deposit_receipt

        event = CoopIpnEvent.objects.get(pk=event_id)
        if event.status != CoopIpnStatus.UNMATCHED:
            self.message_user(
                request,
                f"Event #{event_id} is not unmatched (status: {event.get_status_display()}).",
                level=messages.ERROR,
            )
            return HttpResponseRedirect(
                reverse("admin:payments_coopipnevent_changelist")
            )

        if request.method == "POST":
            form = AssignTenantForm(request.POST)
            if form.is_valid():
                tenant = form.cleaned_data["tenant"]
                try:
                    with db_transaction.atomic():

                        from .coop_ipn import _parse_narration, _posting_date

                        pay_date = _posting_date(event.raw_payload or {})
                        channel = _parse_narration(event.narration).get(
                            "channel", event.channel or "bank"
                        )
                        payments = allocate_payment_fifo(
                            tenant=tenant,
                            amount=event.amount,
                            payment_date=pay_date,
                            source=channel,
                            reference=event.transaction_id,
                            notes=(
                                f"Manually assigned by {request.user}; "
                                f"IPN event #{event.pk}"
                            ),
                        )
                        event.status = CoopIpnStatus.RECORDED
                        event.detail = f"Manually assigned to {tenant} by {request.user}"
                        event.payment = payments[0]
                        event.save(update_fields=["status", "detail", "payment"])

                    # Send the deposit receipt (broker-safe, off the atomic block)
                    try:
                        send_deposit_receipt.delay(
                            tenant.id,
                            str(event.amount),
                            event.transaction_id,
                            pay_date.isoformat(),
                        )
                    except Exception:  # noqa: BLE001
                        pass

                    self.message_user(
                        request,
                        f"KES {event.amount} assigned to {tenant} — payment recorded, receipt queued.",
                        level=messages.SUCCESS,
                    )
                    return HttpResponseRedirect(
                        reverse("admin:payments_coopipnevent_changelist")
                    )
                except Exception as exc:  # noqa: BLE001
                    self.message_user(request, f"Error: {exc}", level=messages.ERROR)
        else:
            form = AssignTenantForm()

        context = {
            **self.admin_site.each_context(request),
            "title": f"Assign unmatched credit — KES {event.amount} ({event.transaction_id})",
            "event": event,
            "form": form,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/payments/coopipnevent/assign_tenant.html",
            context,
        )


@admin.register(TenantNotification)
class TenantNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "tenant", "channel", "status", "template_key", "sent_at", "created_at",
    )
    list_filter = ("channel", "status", "template_key")
    search_fields = (
        "tenant__first_name", "tenant__last_name", "subject", "body",
    )
    readonly_fields = ("created_at", "sent_at")
