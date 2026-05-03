"""Tenant API views — updated with move-out notice, deposit refund, and edit."""
from django.db import models, transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Tenant, TenantDocument, TenantStatus
from .serializers import (
    DocumentUploadSerializer,
    MoveOutNoticeSerializer,
    MoveOutSerializer,
    TenantCreateSerializer,
    TenantDetailSerializer,
    TenantDocumentSerializer,
    TenantEditSerializer,
    TenantListSerializer,
)
from .services import FileValidationError, move_in_tenant, move_out_tenant, validate_upload


def render_to_pdf(template_src, context_dict={}):
    from apps.payments.pdf_service import render_to_pdf as r2p
    return r2p(template_src, context_dict)



class TenantViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Active/notice tenants first, then moved-out, then by move-in date
        qs = (
            Tenant.objects.select_related("unit", "unit__building")
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

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                models.Q(first_name__icontains=search)
                | models.Q(last_name__icontains=search)
                | models.Q(id_number__icontains=search)
                | models.Q(phone__icontains=search)
            )

        return qs

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
        tenant.deposit_refund_amount = tenant.deposit_paid * (refund_pct / 100)
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
            validate_upload(uploaded_file)
        except FileValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        doc = TenantDocument.objects.create(
            tenant=tenant,
            doc_type=ser.validated_data["doc_type"],
            file=uploaded_file,
            original_name=uploaded_file.name,
        )
        return Response(TenantDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="documents/list")
    def list_documents(self, request, pk=None):
        tenant = self.get_object()
        docs = tenant.documents.all()
        return Response(TenantDocumentSerializer(docs, many=True).data)

    @action(detail=True, methods=["get"], url_path="payment-history")
    def payment_history(self, request, pk=None):
        """GET /api/tenants/<id>/payment-history/ — payment analytics for tenant detail page."""
        from apps.payments.models import Arrears, Payment
        from django.db.models import Sum
        tenant = self.get_object()
        payments = Payment.objects.filter(tenant=tenant).order_by("-payment_date")[:24]
        arrears = Arrears.objects.filter(tenant=tenant, is_cleared=False)
        total_paid = tenant.payments.aggregate(total=Sum("amount"))["total"] or 0
        total_arrears = arrears.aggregate(total=Sum("balance"))["total"] or 0
        return Response({
            "total_paid": float(total_paid),
            "total_arrears": float(total_arrears),
            "payments": [
                {
                    "id": p.id,
                    "amount": float(p.amount),
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
                    "expected": float(a.expected_rent),
                    "paid": float(a.amount_paid),
                    "balance": float(a.balance),
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
        running_balance = 0

        # Arrears entries represent the rent obligation for each month
        for c in charges:
            running_balance += float(c.expected_rent)
            ledger.append({
                "date": f"{c.period_year}-{c.period_month:02d}-01",
                "description": f"Rent Charge - {c.period_month}/{c.period_year}",
                "type": "debit",
                "amount": float(c.expected_rent),
                "running_balance": running_balance,
                "period": f"{c.period_month}/{c.period_year}"
            })

        # Payment entries reduce the balance
        for p in credits:
            running_balance -= float(p.amount)
            ledger.append({
                "date": p.payment_date.isoformat(),
                "description": f"Rent Payment - {p.source.upper()} ({p.reference or 'N/A'})",
                "type": "credit",
                "amount": float(p.amount),
                "running_balance": running_balance,
                "period": f"{p.period_month}/{p.period_year}"
            })

        # Sort by date, then by type (debit/charge first on same day)
        ledger.sort(key=lambda x: (x["date"], 0 if x["type"] == "debit" else 1))

        return Response({
            "tenant_name": tenant.full_name,
            "unit": tenant.unit.label if tenant.unit else "N/A",
            "building": tenant.unit.building.name if tenant.unit else "N/A",
            "total_expected": sum(float(c.expected_rent) for c in charges),
            "total_paid": sum(float(p.amount) for p in credits),
            "current_balance": running_balance,
            "entries": ledger
        })

    @action(detail=True, methods=["get"], url_path="statement-pdf")
    def statement_pdf(self, request, pk=None):
        """GET /api/tenants/<id>/statement-pdf/"""
        from django.http import HttpResponse
        
        # Reuse the statement logic by calling the method
        res = self.statement(request, pk=pk)
        data = res.data
        
        pdf = render_to_pdf("payments/statement_pdf.html", data)
        if pdf:
            filename = f"Statement_{data['tenant_name'].replace(' ', '_')}.pdf"
            response = HttpResponse(pdf, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        return Response({"detail": "PDF generation failed."}, status=500)

