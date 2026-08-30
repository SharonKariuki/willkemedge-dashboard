"""Tenant serializers — updated with deposit refund, notice, and edit fields."""
from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers

from .models import DocumentType, Tenant, TenantDocument


def _money(value) -> str:
    """Quantize a monetary value to 2 dp and return it as an exact string."""
    return str(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def outstanding_balance(tenant):
    """Sum of the tenant's uncleared arrears balances."""
    from django.db.models import Sum
    return tenant.arrears.filter(is_cleared=False).aggregate(total=Sum("balance"))["total"] or 0


def live_payments(tenant):
    """Payments that still count — a voided payment is money that never was.

    ``Payment`` rows are immutable, so a mistake is unwound by stamping
    ``voided_at`` and posting a mirror journal entry. Every balance, arrears and
    income figure excludes them; ``total_paid`` did not, so a voided receipt kept
    inflating the tenant's paid-to-date long after it had been reversed.
    """
    return tenant.payments.filter(voided_at__isnull=True)


class TenantDocumentSerializer(serializers.ModelSerializer):
    doc_type_display = serializers.CharField(source="get_doc_type_display", read_only=True)

    class Meta:
        model = TenantDocument
        fields = ["id", "tenant", "doc_type", "doc_type_display", "file", "original_name", "uploaded_at"]
        read_only_fields = ["tenant", "original_name", "uploaded_at"]


class TenantListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    building_name = serializers.CharField(source="unit.building.name", read_only=True)
    building_id = serializers.IntegerField(source="unit.building.id", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    kyc_status_display = serializers.CharField(source="get_kyc_status_display", read_only=True)
    balance = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id", "full_name", "first_name", "last_name", "phone", "email",
            "unit", "unit_label", "building_name", "building_id",
            "monthly_rent", "deposit_paid", "due_day", "status", "status_display",
            "kyc_status", "kyc_status_display", "balance", "payment_status",
            "move_in_date", "move_out_date", "notice_date", "intended_move_out_date",

        ]

    def _outstanding(self, obj):
        """Uncleared arrears balance — prefers the queryset annotation,
        falls back to a query if the object was fetched without it."""
        balance = getattr(obj, "outstanding_balance", None)
        if balance is None:
            balance = outstanding_balance(obj)
        return balance or 0

    def get_balance(self, obj):
        return _money(self._outstanding(obj))

    def get_payment_status(self, obj):
        return "in_arrears" if self._outstanding(obj) > 0 else "paid"


class TenantDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    unit_label = serializers.CharField(source="unit.label", read_only=True)
    building_name = serializers.CharField(source="unit.building.name", read_only=True)
    building_id = serializers.IntegerField(source="unit.building.id", read_only=True)
    # Commercial and residential lettings differ on the page: commercial is
    # VAT-rated and takes a three-month deposit against the residential one, so
    # the detail view needs to know which it is rather than inferring it from
    # whatever figures happen to be loaded.
    unit_classification = serializers.CharField(source="unit.classification", read_only=True)
    # What the deposit SHOULD be, so the card has something to hold `deposit_paid`
    # against. Derived, never stored: the rule is policy and `deposit_paid` is
    # cash received, and conflating them is how an unquestioned figure survives.
    deposit_months = serializers.SerializerMethodField()
    expected_deposit = serializers.SerializerMethodField()
    deposit_shortfall = serializers.SerializerMethodField()
    # Set when the landlord agreed a figure the rule does not produce, in which
    # case `expected_deposit` IS that figure and describing it as months of rent
    # would be a lie.
    deposit_is_agreed = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    documents = TenantDocumentSerializer(many=True, read_only=True)
    # Payment analytics
    total_paid = serializers.SerializerMethodField()
    total_arrears = serializers.SerializerMethodField()
    # Mirrors TenantListSerializer. The detail page drives its arrears styling
    # and the "Remind" button off this field; omitting it left every tenant
    # reading as `undefined` — arrears rendered in the green "all paid" colour
    # and the reminder button was unreachable no matter how much was owed.
    payment_status = serializers.SerializerMethodField()
    # KYC
    kyc_status_display = serializers.CharField(source="get_kyc_status_display", read_only=True)
    kyc_complete = serializers.BooleanField(read_only=True)
    kyc_missing_items = serializers.ListField(child=serializers.CharField(), read_only=True)
    kyc_verified_by_name = serializers.CharField(source="kyc_verified_by.get_full_name", read_only=True, default=None)

    class Meta:
        model = Tenant
        fields = [
            "id", "full_name", "first_name", "last_name", "id_number", "kra_pin",
            "phone", "email", "emergency_contact", "emergency_phone", "care_of",
            "unit", "unit_label", "building_name", "building_id", "unit_classification",
            "monthly_rent", "deposit_paid", "due_day",
            "deposit_months", "expected_deposit", "deposit_shortfall",
            "agreed_deposit", "deposit_is_agreed",

            "deposit_refund_percentage", "deposit_refund_amount",
            "move_in_date", "move_out_date",
            "notice_date", "intended_move_out_date",
            "status", "status_display", "move_out_notes", "notes",
            "kyc_status", "kyc_status_display", "kyc_complete", "kyc_missing_items",
            "kyc_verified_at", "kyc_verified_by", "kyc_verified_by_name", "kyc_notes",
            "documents", "total_paid", "total_arrears", "payment_status",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "status", "move_out_date", "move_out_notes", "created_at", "updated_at",
            "kyc_status", "kyc_verified_at", "kyc_verified_by", "kyc_notes",
        ]

    def get_deposit_months(self, obj):
        from apps.tenants.deposits import deposit_months
        return deposit_months(obj)

    def get_expected_deposit(self, obj):
        from apps.tenants.deposits import expected_deposit
        return _money(expected_deposit(obj))

    def get_deposit_shortfall(self, obj):
        from apps.tenants.deposits import deposit_shortfall
        return _money(deposit_shortfall(obj))

    def get_deposit_is_agreed(self, obj):
        from apps.tenants.deposits import has_agreed_deposit
        return has_agreed_deposit(obj)

    def get_total_paid(self, obj):
        from django.db.models import Sum
        result = live_payments(obj).aggregate(total=Sum("amount"))["total"]
        return _money(result)

    def get_total_arrears(self, obj):
        return _money(outstanding_balance(obj))

    def get_payment_status(self, obj):
        return "in_arrears" if outstanding_balance(obj) > 0 else "paid"


class TenantCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "id", "first_name", "last_name", "id_number", "kra_pin", "phone", "email",
            "emergency_contact", "emergency_phone", "unit",
            "monthly_rent", "deposit_paid", "due_day", "move_in_date", "notes",

        ]

    def validate_unit(self, unit):
        from apps.buildings.models import UnitStatus
        if unit.status not in (UnitStatus.VACANT,):
            raise serializers.ValidationError("This unit is not vacant.")
        if Tenant.objects.filter(unit=unit, status__in=["active", "notice_given"]).exists():
            raise serializers.ValidationError("This unit already has an active tenant.")
        return unit


class TenantEditSerializer(serializers.ModelSerializer):
    """For admin editing of tenant details — rent, deposit, status."""

    # An empty box means "back to the rule", not "agreed at zero" — a blank
    # arrives from the form as "" and would otherwise be rejected outright.
    agreed_deposit = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0,
        required=False, allow_null=True,
    )

    class Meta:
        model = Tenant
        fields = [
            "first_name", "last_name", "kra_pin", "phone", "email",
            "emergency_contact", "emergency_phone", "care_of",
            "monthly_rent", "deposit_paid", "agreed_deposit", "due_day",
            "deposit_refund_percentage",
            "notes",

        ]

    def to_internal_value(self, data):
        if data.get("agreed_deposit") in ("", " "):
            data = data.copy()
            data["agreed_deposit"] = None
        return super().to_internal_value(data)


class MoveOutNoticeSerializer(serializers.Serializer):
    """Record that a tenant has given move-out notice."""
    notice_date = serializers.DateField()
    intended_move_out_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class MoveOutSerializer(serializers.Serializer):
    """Finalise move-out."""
    move_out_date = serializers.DateField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    deposit_refund_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=100)


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    doc_type = serializers.ChoiceField(choices=DocumentType.choices, default=DocumentType.OTHER)


class KycRejectSerializer(serializers.Serializer):
    """Reason is required when rejecting a tenant's KYC."""
    reason = serializers.CharField()
