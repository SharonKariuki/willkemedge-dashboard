"""``set_rent_month`` and ``remove_adjustments`` — restating months already
charged, and taking out hand-entered balancing entries."""
import datetime as dt
import io
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.ledger.models import JournalLine
from apps.payments import credits
from apps.payments.models import Arrears, CreditReason, TenantCredit, UtilityCharge
from apps.tenants.models import Tenant, TenantStatus


def _tenant(label, *, classification=UnitClassification.BUSINESS, rent="25000", status=TenantStatus.ACTIVE):
    building = Building.objects.create(name=f"B-{label}", code=label[:3], total_floors=1)
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal(rent),
        classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Test", last_name=label, id_number=f"ID-{label}", phone="+254700000002",
        unit=unit, monthly_rent=Decimal(rent), move_in_date="2026-06-01", status=status,
    )


def _bill(tenant, month, rent, vat):
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=2026,
        expected_rent=Decimal(rent), expected_vat=Decimal(vat), amount_paid=Decimal("0"),
        balance=Decimal(rent) + Decimal(vat), is_cleared=False,
    )


def _run(name, *args):
    out = io.StringIO()
    call_command(name, *args, stdout=out)
    return out.getvalue()


def _account(code, **filters):
    t = JournalLine.objects.filter(account__code=code, **filters).aggregate(dr=Sum("debit"), cr=Sum("credit"))
    return (t["dr"] or 0) - (t["cr"] or 0)


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(
        username="owner", email="owner@test.com", password="testpass123!", role="owner"
    )


@pytest.mark.django_db
class TestSetRentMonth:
    def test_preview_writes_nothing(self):
        tenant = _tenant("MCT10")
        row = _bill(tenant, 10, "25000", "4000")
        out = _run("set_rent_month", "MCT10", "2026-10", "--rent", "30000")
        assert "rent 25,000.00 + VAT 4,000.00 -> rent 30,000.00 + VAT 4,800.00" in out
        row.refresh_from_db()
        assert row.expected_rent == Decimal("25000.00")

    def test_apply_restates_the_month_and_the_ledger(self):
        tenant = _tenant("MCT10")
        row = _bill(tenant, 10, "25000", "4000")
        _run("set_rent_month", "MCT10", "2026-10", "--rent", "30,000", "--apply")
        row.refresh_from_db()
        assert (row.expected_rent, row.expected_vat, row.balance) == (
            Decimal("30000.00"), Decimal("4800.00"), Decimal("34800.00"))
        lines = {"entry__source_type": "arrear", "entry__source_id": row.pk}
        assert _account("1040", **lines) == Decimal("34800.00")
        assert _account("2600", **lines) == Decimal("-4800.00")

    def test_raises_a_missing_month_on_a_moved_out_letting(self):
        tenant = _tenant("MCT12", rent="50655", status=TenantStatus.MOVED_OUT)
        with pytest.raises(CommandError, match="--tenant-id"):
            _run("set_rent_month", "MCT12", "2026-10", "--rent", "50655")
        _run("set_rent_month", "MCT12", "2026-10", "--rent", "50655", "--tenant-id", str(tenant.pk), "--apply")
        row = Arrears.objects.get(tenant=tenant, period_year=2026, period_month=10)
        assert (row.expected_rent, row.expected_vat) == (Decimal("50655.00"), Decimal("8104.80"))

    def test_raised_month_is_paid_from_money_banked_ahead(self):
        from apps.payments.models import Payment, PaymentSource, PaymentType
        from apps.payments.services import _update_arrears

        tenant = _tenant("MCT07", rent="60000")
        _bill(tenant, 10, "60000", "9600")
        Payment.objects.create(
            tenant=tenant, amount=Decimal("139200"), payment_date="2026-10-23",
            period_month=10, period_year=2026, source=PaymentSource.BANK,
            payment_type=PaymentType.RENT, reference="QTR1",
        )
        _update_arrears(tenant, 10, 2026)
        _run("set_rent_month", "MCT07", "2026-11", "--rent", "60000", "--apply")
        row = Arrears.objects.get(tenant=tenant, period_month=11)
        assert row.balance == Decimal("0.00") and row.is_cleared

    def test_residential_month_carries_no_vat(self):
        _tenant("MRT01", classification=UnitClassification.RESIDENTIAL, rent="27000")
        _run("set_rent_month", "MRT01", "2026-11", "--rent", "27000", "--apply")
        row = Arrears.objects.get(tenant__unit__label="MRT01", period_month=11)
        assert row.expected_vat == Decimal("0")

    def test_lowering_keeps_the_money_paid(self):
        tenant = _tenant("MCT05")
        row = _bill(tenant, 11, "185260", "29641.60")
        _run("set_rent_month", "MCT05", "2026-11", "--rent", "106500", "--apply")
        row.refresh_from_db()
        assert row.expected_total == Decimal("123540.00")
        assert row.balance == Decimal("123540.00")

    def test_refuses_before_first_rent_month(self):
        tenant = _tenant("MCT08")
        tenant.first_rent_month = dt.date(2026, 11, 1)
        tenant.save(update_fields=["first_rent_month"])
        with pytest.raises(CommandError, match="rent starts 11/2026"):
            _run("set_rent_month", "MCT08", "2026-10", "--rent", "50655")

    def test_refuses_below_credit_notes(self, owner):
        tenant = _tenant("MCT11")
        row = _bill(tenant, 10, "25000", "4000")
        credits.issue_credit(
            tenant=tenant, reason=CreditReason.BILLING_CORRECTION, net_amount="20000",
            credit_date=dt.date(2026, 10, 20), description="Correction", actor=owner, arrears=row,
        )
        with pytest.raises(CommandError, match="Credit notes have already taken"):
            _run("set_rent_month", "MCT11", "2026-10", "--rent", "10000")


@pytest.mark.django_db
class TestRemoveAdjustments:
    def _charge(self, tenant, amount="4400"):
        return UtilityCharge.objects.create(
            tenant=tenant, posting_date=dt.date(2026, 10, 24), period_month=10, period_year=2026,
            label="Billing after system Reconciliation", amount=Decimal(amount),
        )

    def _credit(self, tenant, owner, amount="1200"):
        return credits.issue_credit(
            tenant=tenant, reason=CreditReason.OPENING_CREDIT, net_amount=amount,
            credit_date=dt.date(2026, 10, 24), description="Credit after reconciliation", actor=owner,
        )

    def test_preview_keeps_everything(self, owner):
        tenant = _tenant("MRT02", classification=UnitClassification.RESIDENTIAL)
        charge, credit = self._charge(tenant), self._credit(tenant, owner)
        out = _run("remove_adjustments", "--charge", str(charge.pk), "--credit", credit.number, "--reason", "test")
        assert f"delete charge {charge.pk} MRT02" in out and f"void credit {credit.number}" in out
        assert UtilityCharge.objects.filter(pk=charge.pk).exists()
        credit.refresh_from_db()
        assert not credit.is_void

    def test_apply_removes_and_the_ledger_follows(self, owner):
        tenant = _tenant("MRT02", classification=UnitClassification.RESIDENTIAL)
        charge, credit = self._charge(tenant), self._credit(tenant, owner)
        _run("remove_adjustments", "--charge", str(charge.pk), "--credit", credit.number,
             "--reason", "Replaced by opening balance", "--apply")
        assert not UtilityCharge.objects.filter(pk=charge.pk).exists()
        credit.refresh_from_db()
        assert credit.is_void and credit.void_reason == "Replaced by opening balance"
        assert _account("1040", entry__source_type="utility_charge", entry__source_id=charge.pk) == 0
        assert TenantCredit.objects.filter(tenant=tenant, status="issued").count() == 0

    def test_unknown_id_writes_nothing(self, owner):
        tenant = _tenant("MRT02", classification=UnitClassification.RESIDENTIAL)
        charge = self._charge(tenant)
        with pytest.raises(CommandError, match="Not found: CR-99999"):
            _run("remove_adjustments", "--charge", str(charge.pk), "--credit", "CR-99999",
                 "--reason", "x", "--apply")
        assert UtilityCharge.objects.filter(pk=charge.pk).exists()

    def test_charge_with_a_credit_note_is_refused(self, owner):
        tenant = _tenant("MRT02", classification=UnitClassification.RESIDENTIAL)
        charge = self._charge(tenant)
        credits.issue_credit(
            tenant=tenant, reason=CreditReason.BILLING_CORRECTION, net_amount="400",
            credit_date=dt.date(2026, 10, 25), description="Water", actor=owner, utility_charge=charge,
        )
        with pytest.raises(CommandError, match="credit note is issued against it"):
            _run("remove_adjustments", "--charge", str(charge.pk), "--reason", "x", "--apply")
