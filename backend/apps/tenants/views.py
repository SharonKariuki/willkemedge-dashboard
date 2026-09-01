"""Tenant API views — updated with move-out notice, deposit refund, and edit."""
from decimal import ROUND_HALF_UP, Decimal

from django.db import models, transaction
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Tenant, TenantDocument, TenantStatus
from .serializers import (
    DocumentUploadSerializer,
    KycRejectSerializer,
    MoveOutNoticeSerializer,
    MoveOutSerializer,
    TenantCreateSerializer,
    TenantDetailSerializer,
    TenantDocumentSerializer,
    TenantEditSerializer,
    TenantListSerializer,
    rent_roll_balances,
)
from .services import FileValidationError, move_in_tenant, move_out_tenant, validate_upload


def _money(value) -> str:
    """Quantize a monetary value to 2 dp and return it as a string.

    Money is kept in Decimal end-to-end to avoid binary float drift; we
    serialize as a string so the JSON value is exact (e.g. "10000.00").
    """
    return str(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def render_to_pdf(template_src, context_dict=None):
    if context_dict is None:
        context_dict = {}
    from apps.payments.pdf_service import render_to_pdf as r2p
    return r2p(template_src, context_dict)




class TenantViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Active/notice tenants first, then moved-out, then by move-in date.
        # `outstanding_balance` = sum of uncleared arrears (positive = owed);
        # drives the paid/in-arrears filter and the balance column/CSV.
        qs = (
            Tenant.objects.select_related("unit", "unit__building")
            .annotate(
                outstanding_balance=Coalesce(
                    models.Sum(
                        "arrears__balance",
                        filter=models.Q(arrears__is_cleared=False),
                    ),
                    models.Value(Decimal("0.00")),
                    output_field=models.DecimalField(max_digits=12, decimal_places=2),
                )
            )
            .order_by(
                models.Case(
                    models.When(status="active", then=0),
                    models.When(status="notice_given", then=1),
                    models.When(status="moved_out", then=2),
                    default=3,
                    output_field=models.IntegerField(),
                ),
                "-move_in_date",
            )
        )

        tenant_status = self.request.query_params.get("status")
        if tenant_status:
            qs = qs.filter(status=tenant_status)

        building_id = self.request.query_params.get("building")
        if building_id:
            qs = qs.filter(unit__building_id=building_id)

        unit_id = self.request.query_params.get("unit")
        if unit_id:
            qs = qs.filter(unit_id=unit_id)

        kyc = self.request.query_params.get("kyc_status")
        if kyc:
            qs = qs.filter(kyc_status=kyc)

        payment_status = self.request.query_params.get("payment_status")
        if payment_status == "in_arrears":
            qs = qs.filter(outstanding_balance__gt=0)
        elif payment_status == "paid":
            qs = qs.filter(outstanding_balance__lte=0)

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                models.Q(first_name__icontains=search)
                | models.Q(last_name__icontains=search)
                | models.Q(id_number__icontains=search)
                | models.Q(phone__icontains=search)
            )

        return qs

    def get_serializer_context(self):
        """Price the whole page's balances in one go.

        ``TenantListSerializer`` falls back to a per-row lookup when this is
        absent, which is correct but issues three queries a tenant. Batching
        here keeps the list at three queries however long it gets.
        """
        context = super().get_serializer_context()
        if self.action == "list":
            page = getattr(self, "_page_for_balances", None)
            if page is not None:
                context["rent_roll_balances"] = rent_roll_balances(page)
        return context

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        self._page_for_balances = page if page is not None else list(queryset)
        return page

    def list(self, request, *args, **kwargs):
        # An unpaginated list never reaches paginate_queryset with a page, so
        # make sure the batch is primed either way.
        if getattr(self, "_page_for_balances", None) is None and self.paginator is None:
            self._page_for_balances = list(self.filter_queryset(self.get_queryset()))
        return super().list(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TenantDetailSerializer
        if self.action == "create":
            return TenantCreateSerializer
        if self.action in ("partial_update", "update"):
            return TenantEditSerializer
        return TenantListSerializer

    def perform_create(self, serializer):
        tenant = serializer.save()
        move_in_tenant(tenant)

    @action(detail=False, methods=["get"], url_path="export")
    def export_csv(self, request):
        """GET /api/tenants/export/ — CSV of the (filtered) tenant list.

        Honors the same query params as the list endpoint (status, building,
        unit, kyc_status, search, payment_status), so the export always
        mirrors what the manager currently sees on screen.
        """
        import csv

        from django.http import HttpResponse

        qs = list(self.get_queryset())
        balances = rent_roll_balances(qs)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="tenants.csv"'
        writer = csv.writer(response)
        writer.writerow(["Tenant", "Building", "Unit", "Balance", "Payment Status", "Status"])
        for t in qs:
            balance = balances.get(t.pk, Decimal("0.00"))
            arrears_balance = getattr(t, "outstanding_balance", None) or 0
            payment_status = "In Arrears" if arrears_balance > 0 else "Paid"
            writer.writerow([
                t.full_name,
                t.unit.building.name,
                t.unit.label,
                _money(balance),
                payment_status,
                t.get_status_display(),
            ])
        return response

    @action(detail=True, methods=["post"], url_path="move-out-notice")
    def move_out_notice(self, request, pk=None):
        """POST /api/tenants/<id>/move-out-notice/ — record notice of intention to move out."""
        tenant = self.get_object()
        if not tenant.is_active:
            return Response({"detail": "Tenant is not active."}, status=status.HTTP_400_BAD_REQUEST)
        ser = MoveOutNoticeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant.notice_date = ser.validated_data["notice_date"]
        tenant.intended_move_out_date = ser.validated_data["intended_move_out_date"]
        tenant.status = TenantStatus.NOTICE_GIVEN
        if ser.validated_data.get("notes"):
            tenant.move_out_notes = ser.validated_data["notes"]
        tenant.save(update_fields=["status", "notice_date", "intended_move_out_date", "move_out_notes"])
        return Response(TenantDetailSerializer(tenant).data)

    @action(detail=True, methods=["post"], url_path="move-out")
    def move_out(self, request, pk=None):
        """POST /api/tenants/<id>/move-out/ — finalise move-out with deposit refund %."""
        tenant = self.get_object()
        if not tenant.is_active:
            return Response({"detail": "Tenant is not active."}, status=status.HTTP_400_BAD_REQUEST)
        ser = MoveOutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        # Calculate deposit refund
        refund_pct = ser.validated_data.get("deposit_refund_percentage", 100)
        tenant.deposit_refund_percentage = refund_pct
        tenant.deposit_refund_amount = tenant.deposit_paid * (Decimal(refund_pct) / Decimal(100))
        tenant.save(update_fields=["deposit_refund_percentage", "deposit_refund_amount"])

        with transaction.atomic():
            move_out_tenant(
                tenant,
                move_out_date=ser.validated_data.get("move_out_date"),
                notes=ser.validated_data.get("notes", ""),
            )
        return Response(TenantDetailSerializer(tenant).data)

    @action(detail=True, methods=["post"], url_path="documents", parser_classes=[MultiPartParser, FormParser])
    def upload_document(self, request, pk=None):
        tenant = self.get_object()
        ser = DocumentUploadSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        uploaded_file = ser.validated_data["file"]
        try:
            safe_name = validate_upload(uploaded_file)
        except FileValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        # Store under a sanitized name so the path can't be manipulated, and
        # keep a sanitized original_name (never the raw client value).
        uploaded_file.name = safe_name
        doc = TenantDocument.objects.create(
            tenant=tenant,
            doc_type=ser.validated_data["doc_type"],
            file=uploaded_file,
            original_name=safe_name,
        )
        # Auto-advance KYC to "pending review" once the minimum identity data is on file.
        tenant.submit_kyc()
        return Response(TenantDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="verify-kyc")
    def verify_kyc(self, request, pk=None):
        """POST /api/tenants/<id>/verify-kyc/ — admin confirms identity is verified."""
        tenant = self.get_object()
        missing = tenant.kyc_missing_items
        if missing:
            return Response(
                {"detail": "Cannot verify — still missing: " + ", ".join(missing)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        tenant.mark_kyc_verified(request.user)
        return Response(TenantDetailSerializer(tenant).data)

    @action(detail=True, methods=["post"], url_path="reject-kyc")
    def reject_kyc(self, request, pk=None):
        """POST /api/tenants/<id>/reject-kyc/ — admin rejects with a reason."""
        tenant = self.get_object()
        ser = KycRejectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant.reject_kyc(request.user, ser.validated_data["reason"])
        return Response(TenantDetailSerializer(tenant).data)

    @action(detail=True, methods=["get"], url_path="documents/list")
    def list_documents(self, request, pk=None):
        tenant = self.get_object()
        docs = tenant.documents.all()
        return Response(TenantDocumentSerializer(docs, many=True).data)

    @action(detail=True, methods=["get"], url_path=r"documents/(?P<doc_id>[0-9]+)/download")
    def download_document(self, request, pk=None, doc_id=None):
        """GET /api/tenants/<id>/documents/<doc_id>/download/ — stream a KYC document.

        Authenticated-only (IsAuthenticated on the viewset). We serve the file
        through FileResponse rather than relying on static/media serving so the
        document is never reachable via a guessable URL.
        """
        from django.http import FileResponse, Http404

        tenant = self.get_object()
        try:
            doc = tenant.documents.get(pk=doc_id)
        except TenantDocument.DoesNotExist as exc:
            raise Http404("Document not found.") from exc
        if not doc.file:
            raise Http404("Document file is missing.")
        # original_name is already sanitized on upload.
        return FileResponse(
            doc.file.open("rb"),
            as_attachment=True,
            filename=doc.original_name or "document",
        )

    @action(detail=True, methods=["get"], url_path="payment-history")
    def payment_history(self, request, pk=None):
        """GET /api/tenants/<id>/payment-history/ — payment analytics for tenant detail page."""
        from django.db.models import Sum

        from apps.payments.models import Arrears, Payment
        from apps.payments.monthly_ledger import build_monthly_ledger
        tenant = self.get_object()
        payments = (
            Payment.objects.filter(tenant=tenant, voided_at__isnull=True)
            .order_by("-payment_date")[:24]
        )
        arrears = Arrears.objects.filter(tenant=tenant, is_cleared=False)
        # Voided payments are excluded from every other balance in the system;
        # counting them here made paid-to-date disagree with the arrears table.
        total_paid = (
            tenant.payments.filter(voided_at__isnull=True)
            .aggregate(total=Sum("amount"))["total"] or Decimal("0")
        )
        total_arrears = arrears.aggregate(total=Sum("balance"))["total"] or Decimal("0")
        return Response({
            "total_paid": _money(total_paid),
            "total_arrears": _money(total_arrears),
            # Deposit held — the "Rent Security Deposit" column of the rent roll.
            "security_deposit": _money(tenant.deposit_paid),
            # Month-by-month rent roll; extends itself as billing posts periods.
            "monthly_ledger": build_monthly_ledger(tenant),
            "payments": [
                {
                    "id": p.id,
                    "amount": _money(p.amount),
                    "payment_date": p.payment_date.isoformat(),
                    "period_month": p.period_month,
                    "period_year": p.period_year,
                    "source": p.source,
                    "reference": p.reference,
                }
                for p in payments
            ],
            "arrears": [
                {
                    "period": f"{a.period_month}/{a.period_year}",
                    # The full obligation, rent + VAT. A commercial tenant pays
                    # the VAT-inclusive figure and `balance` is measured against
                    # it, so showing base rent alone made the row contradict
                    # itself on screen: expected 15,000 less paid 6,990 was
                    # displayed beside a balance of 10,410.
                    "expected": _money(a.expected_total),
                    "expected_rent": _money(a.expected_rent),
                    "expected_vat": _money(a.expected_vat),
                    "paid": _money(a.amount_paid),
                    "balance": _money(a.balance),
                }
                for a in arrears
            ],
        })
    @action(detail=True, methods=["get"], url_path="statement")
    def statement(self, request, pk=None):
        """GET /api/tenants/<id>/statement/ — unified financial ledger."""
        from apps.payments.models import Arrears, Payment
        tenant = self.get_object()

        # Charges (Arrears records)
        charges = Arrears.objects.filter(tenant=tenant).order_by("period_year", "period_month")
        # Credits (Payments)
        credits = Payment.objects.filter(tenant=tenant).order_by("payment_date")

        ledger = []
        running_balance = Decimal("0")

        # Arrears entries represent the rent obligation for each month
        for c in charges:
            running_balance += c.expected_rent
            ledger.append({
                "date": f"{c.period_year}-{c.period_month:02d}-01",
                "description": f"Rent Charge - {c.period_month}/{c.period_year}",
                "type": "debit",
                "amount": _money(c.expected_rent),
                "running_balance": _money(running_balance),
                "period": f"{c.period_month}/{c.period_year}"
            })

        # Payment entries reduce the balance
        for p in credits:
            running_balance -= p.amount
            ledger.append({
                "date": p.payment_date.isoformat(),
                "description": f"Rent Payment - {p.source.upper()} ({p.reference or 'N/A'})",
                "type": "credit",
                "amount": _money(p.amount),
                "running_balance": _money(running_balance),
                "period": f"{p.period_month}/{p.period_year}"
            })

        # Sort by date, then by type (debit/charge first on same day)
        ledger.sort(key=lambda x: (x["date"], 0 if x["type"] == "debit" else 1))

        total_expected = sum((c.expected_rent for c in charges), Decimal("0"))
        total_paid = sum((p.amount for p in credits), Decimal("0"))
        return Response({
            "tenant_name": tenant.full_name,
            "unit": tenant.unit.label if tenant.unit else "N/A",
            "building": tenant.unit.building.name if tenant.unit else "N/A",
            "total_expected": _money(total_expected),
            "total_paid": _money(total_paid),
            "current_balance": _money(running_balance),
            "entries": ledger
        })

    @action(detail=True, methods=["get"], url_path="statement-pdf")
    def statement_pdf(self, request, pk=None):
        """GET /api/tenants/<id>/statement-pdf/ — official Wilkem rent statement."""
        from django.http import HttpResponse

        from apps.payments.billing_calendar import billing_period
        from apps.payments.statement_service import build_statement

        tenant = self.get_object()
        # The month the cycle is on, so the copy the office downloads is the
        # same statement the tenant was emailed on the 25th rather than the
        # previous month's.
        data = build_statement(tenant, period=billing_period())

        pdf = render_to_pdf("payments/statement_pdf.html", data)
        if pdf:
            filename = f"Rent_Statement_{tenant.full_name.replace(' ', '_')}.pdf"
            response = HttpResponse(pdf, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        return Response({"detail": "PDF generation failed."}, status=500)


    # ── Emailing the statement ───────────────────────────────────────────────
    # The scheduled monthly run lives in payments.tasks.send_monthly_statements.
    # These two are the manual path: the office picks who gets one and when.
    # Both send with automatic=False, so a deliberate send from the dashboard is
    # not silenced by TENANT_NOTIFICATIONS_ENABLED, and neither passes a
    # dedupe_key — re-sending a statement on request is a normal thing to do.

    @action(detail=True, methods=["post"], url_path="email-statement")
    def email_statement(self, request, pk=None):
        """POST /api/tenants/<id>/email-statement/ — email this tenant their statement."""
        from apps.payments.notification_views import TenantNotificationSerializer
        from apps.payments.statement_delivery import send_tenant_statement

        tenant = self.get_object()
        notification = send_tenant_statement(
            tenant,
            automatic=False,
            created_by=request.user if request.user.is_authenticated else None,
        )
        sent = notification.status == "sent"
        return Response(
            {
                "sent": 1 if sent else 0,
                "failed": 0 if sent else 1,
                "total": 1,
                "notifications": [TenantNotificationSerializer(notification).data],
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="email-statements")
    def email_statements(self, request):
        """POST /api/tenants/email-statements/ — email a chosen set of tenants.

        Body: {"tenant_ids": [1, 2, 3]}

        Every id is reported on, including ones that could not be sent, so the
        UI can name the tenants who need an email address rather than just
        showing a count that does not add up.
        """
        from apps.payments.notification_views import TenantNotificationSerializer
        from apps.payments.statement_delivery import (
            open_mail_connection,
            send_tenant_statement,
        )

        raw_ids = request.data.get("tenant_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return Response(
                {"detail": "Provide tenant_ids as a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            tenant_ids = [int(i) for i in raw_ids]
        except (TypeError, ValueError):
            return Response(
                {"detail": "tenant_ids must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Cap the batch: each statement renders a PDF, and the request is
        # synchronous. The whole roster is ~80, so this only ever trips on a
        # malformed or malicious payload.
        if len(tenant_ids) > 200:
            return Response(
                {"detail": "Too many tenants in one send — select 200 or fewer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenants = Tenant.objects.filter(id__in=tenant_ids).select_related(
            "unit", "unit__building"
        )
        if not tenants:
            return Response(
                {"detail": "No tenants matched."}, status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user if request.user.is_authenticated else None
        # One SMTP connection for the whole batch. The handshake, not the PDF,
        # is what makes a property-wide send slow, and this request is
        # synchronous — the office is watching a spinner while it runs.
        with open_mail_connection() as mail:
            results = [
                send_tenant_statement(
                    tenant, automatic=False, created_by=user, connection=mail
                )
                for tenant in tenants
            ]
        sent = sum(1 for n in results if n.status == "sent")

        return Response(
            {
                "sent": sent,
                "failed": len(results) - sent,
                "total": len(results),
                "notifications": TenantNotificationSerializer(results, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )
