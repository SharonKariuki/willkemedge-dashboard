"""A commercial letting the landlord does not charge VAT on (MCG02).

``Tenant.vat_exempt`` stops new rent charges carrying 16% VAT;
``clear_vat`` restates the months already raised, and the ledger's 2600 VAT
payable follows.
"""
import io
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.ledger.models import JournalLine
from apps.payments.models import Arrears, Payment, PaymentSource, PaymentType
from apps.payments.services import expected_vat_for
from apps.tenants.models import Tenant, TenantStatus


def _tenant(*, classification, label, rent="22500"):
    building = Building.objects.create(name=f"B-{label}", code=label[:3], total_floors=1)
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal(rent),
        classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Test", last_name=label, id_number=f"ID-{label}", phone="+254700000001",
        unit=unit, monthly_rent=Decimal(rent), move_in_date="2026-06-01",
        status=TenantStatus.ACTIVE,
    )


def _bill(tenant, month, rent="22500", vat="3600"):
    return Arrears.objects.create(
        tenant=tenant, period_month=month, period_year=2026,
        expected_rent=Decimal(rent), expected_vat=Decimal(vat), amount_paid=Decimal("0"),
        balance=Decimal(rent) + Decimal(vat), is_cleared=False,
    )


def _vat_payable(tenant):
    lines = JournalLine.objects.filter(
        account__code="2600", entry__source_type="arrear",
        entry__source_id__in=Arrears.objects.filter(tenant=tenant).values("pk"),
    ).aggregate(cr=Sum("credit"), dr=Sum("debit"))
    return (lines["cr"] or 0) - (lines["dr"] or 0)


def _run(*args):
    out = io.StringIO()
    call_command("clear_vat", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def commercial(db):
    return _tenant(classification=UnitClassification.BUSINESS, label="MCT02")


@pytest.mark.django_db
class TestNewCharges:
    def test_exempt_letting_is_charged_no_vat(self, commercial):
        assert expected_vat_for(commercial, Decimal("22500")) == Decimal("3600.00")
        commercial.vat_exempt = True
        assert expected_vat_for(commercial, Decimal("22500")) == Decimal("0")

    def test_flag_is_editable_on_the_tenant(self, commercial):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        owner = get_user_model().objects.create_user(
            username="owner", email="owner@test.com", password="testpass123!", role="owner"
        )
        client = APIClient()
        client.force_authenticate(user=owner)
        resp = client.patch(f"/api/tenants/{commercial.pk}/", {"vat_exempt": True}, format="json")
        assert resp.status_code == 200, resp.content
        commercial.refresh_from_db()
        assert commercial.vat_exempt is True
        assert client.get(f"/api/tenants/{commercial.pk}/").json()["vat_exempt"] is True


@pytest.mark.django_db
class TestClearVat:
    def test_preview_writes_nothing(self, commercial):
        row = _bill(commercial, 9)
        out = _run("MCT02", "--from", "2026-09")
        assert "9/2026: VAT 3,600.00 -> 0" in out
        row.refresh_from_db()
        commercial.refresh_from_db()
        assert row.expected_vat == Decimal("3600.00")
        assert commercial.vat_exempt is False

    def test_apply_restates_from_the_month_and_the_ledger_follows(self, commercial):
        august, september, october = _bill(commercial, 8), _bill(commercial, 9), _bill(commercial, 10)
        assert _vat_payable(commercial) == Decimal("10800.00")

        _run("MCT02", "--from", "2026-09", "--apply")

        for row in (august, september, october):
            row.refresh_from_db()
        assert august.expected_vat == Decimal("3600.00")
        assert september.expected_vat == october.expected_vat == Decimal("0.00")
        assert september.balance == Decimal("22500.00")
        assert _vat_payable(commercial) == Decimal("3600.00")
        commercial.refresh_from_db()
        assert commercial.vat_exempt is True

    def test_paid_month_is_cleared_and_rerun_is_a_no_op(self, commercial):
        row = _bill(commercial, 9)
        Payment.objects.create(
            tenant=commercial, amount=Decimal("22500"), payment_date="2026-09-05",
            period_month=9, period_year=2026, source=PaymentSource.BANK,
            payment_type=PaymentType.RENT, reference="VATX1",
        )
        _run("MCT02", "--from", "2026-09", "--apply")
        row.refresh_from_db()
        assert row.balance == Decimal("0.00") and row.is_cleared

        assert "VAT taken off: 0.00" in _run("MCT02", "--from", "2026-09", "--apply")

    def test_residential_unit_is_refused(self, db):
        _tenant(classification=UnitClassification.RESIDENTIAL, label="MRT01")
        with pytest.raises(CommandError, match="not a commercial unit"):
            _run("MRT01", "--from", "2026-09")

    def test_bad_month_is_refused(self, commercial):
        with pytest.raises(CommandError, match="YYYY-MM"):
            _run("MCT02", "--from", "Sept")
