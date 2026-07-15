"""
Tests for 16% VAT posting on commercial rent (Barclay F4).

Acceptance criteria:
  - any rent for a COMMERCIAL (MC) unit computes and posts 16% VAT to the
    correct COA code (2600 VAT Payable)
  - RESIDENTIAL units are not affected (no VAT leg)
  - entries stay balanced
"""
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.ledger.posting import post_arrear, post_payment, reverse_payment
from apps.payments.models import Arrears, Payment, PaymentSource, PaymentType
from apps.tenants.models import Tenant, TenantStatus

VAT_ACCOUNT = "2600"
COMMERCIAL_INCOME = "4120"
RESIDENTIAL_INCOME = "4110"


def _legs(entry):
    """{account_code: (debit, credit)}"""
    return {
        line.account.code: (line.debit, line.credit)
        for line in entry.lines.all()
    }


def _tenant(db, *, classification, label, rent):
    building = Building.objects.create(name=f"B-{label}", code=label[:3], total_floors=1)
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal(rent),
        classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="T", last_name=label, id_number=f"ID{label}",
        phone=f"+2547{label[-6:]:0>6}".replace(" ", "0"),
        unit=unit, monthly_rent=Decimal(rent),
        move_in_date="2026-06-01", status=TenantStatus.ACTIVE,
    )


@pytest.fixture
def commercial_tenant(db):
    return _tenant(db, classification=UnitClassification.BUSINESS, label="MCG01", rent="24000")


@pytest.fixture
def residential_tenant(db):
    return _tenant(db, classification=UnitClassification.RESIDENTIAL, label="DON1A", rent="20000")


@pytest.mark.django_db
class TestCommercialRentPayment:
    def test_vat_split_out_of_gross_receipt(self, commercial_tenant):
        # Tenant pays 27,840 = 24,000 rent + 3,840 VAT.
        pmt = Payment.objects.create(
            tenant=commercial_tenant, amount=Decimal("27840.00"),
            payment_date="2026-06-05", period_month=6, period_year=2026,
            source=PaymentSource.MPESA, payment_type=PaymentType.RENT, reference="MC1",
        )
        legs = _legs(post_payment(pmt))
        assert legs["1020"] == (Decimal("27840.00"), Decimal("0.00"))
        assert legs[COMMERCIAL_INCOME] == (Decimal("0.00"), Decimal("24000.00"))
        assert legs[VAT_ACCOUNT] == (Decimal("0.00"), Decimal("3840.00"))

    def test_entry_balances(self, commercial_tenant):
        pmt = Payment.objects.create(
            tenant=commercial_tenant, amount=Decimal("27840.00"),
            payment_date="2026-06-05", period_month=6, period_year=2026,
            source=PaymentSource.MPESA, payment_type=PaymentType.RENT, reference="MC2",
        )
        entry = post_payment(pmt)
        debits = sum(line.debit for line in entry.lines.all())
        credits = sum(line.credit for line in entry.lines.all())
        assert debits == credits == Decimal("27840.00")

    def test_reversal_mirrors_the_vat_leg(self, commercial_tenant):
        pmt = Payment.objects.create(
            tenant=commercial_tenant, amount=Decimal("27840.00"),
            payment_date="2026-06-05", period_month=6, period_year=2026,
            source=PaymentSource.MPESA, payment_type=PaymentType.RENT, reference="MC3",
        )
        post_payment(pmt)
        legs = _legs(reverse_payment(pmt))
        # Debits and credits flip.
        assert legs[VAT_ACCOUNT] == (Decimal("3840.00"), Decimal("0.00"))
        assert legs[COMMERCIAL_INCOME] == (Decimal("24000.00"), Decimal("0.00"))


@pytest.mark.django_db
class TestCommercialRentBilled:
    def test_arrear_raises_receivable_at_gross_and_credits_vat(self, commercial_tenant):
        arr = Arrears.objects.create(
            tenant=commercial_tenant, period_month=6, period_year=2026,
            expected_rent=Decimal("24000"), amount_paid=Decimal("0"),
            balance=Decimal("24000"), is_cleared=False,
        )
        legs = _legs(post_arrear(arr))
        # Tenant owes rent + VAT, so AR is raised at the gross figure.
        assert legs["1040"] == (Decimal("27840.00"), Decimal("0.00"))
        assert legs[COMMERCIAL_INCOME] == (Decimal("0.00"), Decimal("24000.00"))
        assert legs[VAT_ACCOUNT] == (Decimal("0.00"), Decimal("3840.00"))


@pytest.mark.django_db
class TestResidentialUnaffected:
    def test_payment_has_no_vat_leg(self, residential_tenant):
        pmt = Payment.objects.create(
            tenant=residential_tenant, amount=Decimal("20000.00"),
            payment_date="2026-06-05", period_month=6, period_year=2026,
            source=PaymentSource.MPESA, payment_type=PaymentType.RENT, reference="R1",
        )
        legs = _legs(post_payment(pmt))
        assert VAT_ACCOUNT not in legs
        assert legs[RESIDENTIAL_INCOME] == (Decimal("0.00"), Decimal("20000.00"))

    def test_arrear_has_no_vat_leg(self, residential_tenant):
        arr = Arrears.objects.create(
            tenant=residential_tenant, period_month=6, period_year=2026,
            expected_rent=Decimal("20000"), amount_paid=Decimal("0"),
            balance=Decimal("20000"), is_cleared=False,
        )
        legs = _legs(post_arrear(arr))
        assert VAT_ACCOUNT not in legs
        assert legs["1040"] == (Decimal("20000.00"), Decimal("0.00"))
