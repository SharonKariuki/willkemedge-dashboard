"""
Tenant credits and refunds API — the owner's Add Credit / Refund Credit screens.

    GET  /api/tenant-credits/?tenant=<id>            Credit History list
    GET  /api/tenant-credits/position/?tenant=<id>   Balance card + Add Credit form data
    POST /api/tenant-credits/                        Add Credit (multipart: evidence)
    POST /api/tenant-credits/<id>/hold/              Hold Credit / Apply to Next Invoice
    GET  /api/tenant-credits/<id>/void-preview/      what voiding would do
    POST /api/tenant-credits/<id>/void/              Void Credit (reason required)
    GET  /api/tenant-credits/<id>/evidence/          download the attached evidence

    GET  /api/refunds/?tenant=<id>
    POST /api/refunds/                               Refund Credit
    POST /api/refunds/<id>/mark-sent/                Mark as Sent
    POST /api/refunds/<id>/cancel/                   Cancel Refund (not yet sent)
    POST /api/refunds/<id>/void/                     Void Refund (sent, came back)

Writes are owner-only (``CanForgiveMoney``): credits and refunds forgive or pay
out money, the same privilege as waivers and voids. Reads follow the rest of the
money endpoints — any signed-in user.
"""
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.permissions import CanForgiveMoney
from apps.expenses.models import ExpenseCategory
from apps.tenants.models import Tenant

from . import credits
from .credit_serializers import (
    CreditCreateSerializer,
    HoldSerializer,
    MarkSentSerializer,
    ReasonSerializer,
    RefundCreateSerializer,
    RefundSerializer,
    TenantCreditSerializer,
)
from .models import (
    CREDIT_TYPE_FOR_REASON,
    Arrears,
    CreditApplication,
    CreditReason,
    CreditType,
    Refund,
    RefundLine,
    TenantCredit,
    UtilityCharge,
)
from .monthly_ledger import OPENING_MARKER


def _error(exc) -> Response:
    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


def _period_label(month: int, year: int) -> str:
    import datetime as _dt

    try:
        return _dt.date(year, month, 1).strftime("%B %Y")
    except ValueError:
        return f"{month}/{year}"


class TenantCreditViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanForgiveMoney]
    serializer_class = TenantCreditSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = TenantCredit.objects.select_related(
            "tenant", "arrears", "utility_charge", "expense_category",
            "created_by", "approved_by", "voided_by",
        ).prefetch_related(
            Prefetch("applications", queryset=CreditApplication.objects.select_related("arrears")),
            Prefetch("refund_lines", queryset=RefundLine.objects.select_related("refund")),
        )
        tenant_id = self.request.query_params.get("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        return qs

    def create(self, request):
        from apps.tenants.services import FileValidationError, validate_upload

        ser = CreditCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        evidence = data.get("evidence")
        evidence_name = ""
        if evidence:
            try:
                evidence_name = validate_upload(evidence)
            except FileValidationError as exc:
                return _error(exc)
            evidence.name = evidence_name

        try:
            credit = credits.issue_credit(
                tenant=data["tenant"],
                reason=data["reason"],
                net_amount=data["amount"],
                credit_date=data["credit_date"],
                description=data["description"],
                internal_notes=data.get("internal_notes", ""),
                reference=data.get("reference", ""),
                arrears=data.get("arrears"),
                utility_charge=data.get("utility_charge"),
                expense_category=data.get("expense_category"),
                evidence=evidence,
                evidence_name=evidence_name,
                hold=data.get("hold", False),
                actor=request.user,
            )
        except credits.CreditError as exc:
            return _error(exc)
        credit = self.get_queryset().get(pk=credit.pk)
        return Response(TenantCreditSerializer(credit).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="position")
    def position(self, request):
        """Balance card figures, plus everything the Add Credit form offers."""
        tenant = get_object_or_404(
            Tenant.objects.select_related("unit"), pk=request.query_params.get("tenant")
        )
        rent_rows = []
        for arr in Arrears.objects.filter(tenant=tenant).order_by("-period_year", "-period_month")[:24]:
            if OPENING_MARKER in (arr.waive_notes or ""):
                continue
            rent_rows.append({
                "id": arr.pk,
                "label": f"Rent {_period_label(arr.period_month, arr.period_year)}",
                "charged": arr.expected_rent,
                "vat": arr.expected_vat,
                "creditable": credits.creditable_remaining(arrears=arr),
                "vat_rate": (
                    str((arr.expected_vat / arr.expected_rent).quantize(credits.CENTS * credits.CENTS))
                    if arr.expected_vat and arr.expected_rent else "0"
                ),
            })
        water_rows = [
            {
                "id": u.pk,
                "label": u.description(),
                "charged": u.amount,
                "vat": 0,
                "creditable": credits.creditable_remaining(utility_charge=u),
                "vat_rate": "0",
            }
            for u in UtilityCharge.objects.filter(tenant=tenant, amount__gt=0).order_by("-posting_date", "-id")[:24]
        ]
        reasons = [
            {
                "value": value,
                "label": label,
                "document": CREDIT_TYPE_FOR_REASON[value],
                "needs_charge": CREDIT_TYPE_FOR_REASON[value] == CreditType.CREDIT_NOTE,
                "rent_only": value == CreditReason.RENT_CONCESSION,
                "needs_category": value == CreditReason.TENANT_PAID_COST,
            }
            for value, label in CreditReason.choices
        ]
        categories = [
            {"id": c.pk, "name": c.name}
            for c in ExpenseCategory.objects.filter(account__isnull=False).order_by("name")
        ]
        return Response({
            **{k: str(v) for k, v in credits.credit_position(tenant).items()},
            "reasons": reasons,
            "rent_charges": rent_rows,
            "water_charges": water_rows,
            "expense_categories": categories,
            "tenant_phone": tenant.phone,
        })

    @action(detail=True, methods=["post"])
    def hold(self, request, pk=None):
        credit = self.get_object()
        ser = HoldSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            credits.set_hold(credit, hold=ser.validated_data["hold"], actor=request.user)
        except credits.CreditError as exc:
            return _error(exc)
        return Response(TenantCreditSerializer(self.get_queryset().get(pk=credit.pk)).data)

    @action(detail=True, methods=["get"], url_path="void-preview")
    def void_preview(self, request, pk=None):
        credit = self.get_object()
        preview = credits.void_preview(credit)
        return Response({
            "reopened": [
                {"label": f"Rent {_period_label(r['period_month'], r['period_year'])}", "amount": str(r["amount"])}
                for r in preview["reopened"]
            ],
            "reopened_total": str(preview["reopened_total"]),
            "refunded_kept": str(preview["refunded_kept"]),
            "refunds_cancelled": str(preview["refunds_cancelled"]),
            "tenant_will_owe_more_by": str(preview["tenant_will_owe_more_by"]),
        })

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        credit = self.get_object()
        ser = ReasonSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            credits.void_credit(credit, reason=ser.validated_data["reason"], actor=request.user)
        except credits.CreditError as exc:
            return _error(exc)
        return Response(TenantCreditSerializer(self.get_queryset().get(pk=credit.pk)).data)

    @action(detail=True, methods=["get"])
    def evidence(self, request, pk=None):
        """Stream the attached evidence — never exposed as a guessable media URL."""
        credit = self.get_object()
        if not credit.evidence:
            raise Http404
        try:
            handle = credit.evidence.open("rb")
        except FileNotFoundError:
            raise Http404 from None
        return FileResponse(handle, as_attachment=False, filename=credit.evidence_name or "evidence")


class RefundViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CanForgiveMoney]
    serializer_class = RefundSerializer

    def get_queryset(self):
        qs = Refund.objects.select_related(
            "tenant", "created_by", "sent_recorded_by", "closed_by",
        ).prefetch_related(Prefetch("lines", queryset=RefundLine.objects.select_related("credit")))
        tenant_id = self.request.query_params.get("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        return qs

    def create(self, request):
        ser = RefundCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            refund = credits.create_refund(
                tenant=data["tenant"],
                amount=data["amount"],
                method=data["method"],
                paid_to=data.get("paid_to", ""),
                reference=data.get("reference", ""),
                notes=data.get("notes", ""),
                sent_on=data.get("sent_on") if data["already_sent"] else None,
                credit=data.get("credit"),
                actor=request.user,
            )
        except credits.CreditError as exc:
            return _error(exc)
        return Response(
            RefundSerializer(self.get_queryset().get(pk=refund.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="mark-sent")
    def mark_sent(self, request, pk=None):
        refund = self.get_object()
        ser = MarkSentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            credits.mark_refund_sent(
                refund,
                sent_on=data["sent_on"],
                reference=data.get("reference", ""),
                method=data.get("method"),
                paid_to=data.get("paid_to"),
                actor=request.user,
            )
        except credits.CreditError as exc:
            return _error(exc)
        return Response(RefundSerializer(self.get_queryset().get(pk=refund.pk)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        refund = self.get_object()
        ser = ReasonSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            credits.cancel_refund(refund, reason=ser.validated_data["reason"], actor=request.user)
        except credits.CreditError as exc:
            return _error(exc)
        return Response(RefundSerializer(self.get_queryset().get(pk=refund.pk)).data)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        refund = self.get_object()
        ser = ReasonSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            credits.void_refund(refund, reason=ser.validated_data["reason"], actor=request.user)
        except credits.CreditError as exc:
            return _error(exc)
        return Response(RefundSerializer(self.get_queryset().get(pk=refund.pk)).data)
