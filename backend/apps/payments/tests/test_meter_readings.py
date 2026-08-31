"""
Water billing from meter readings (Barclay F7).

Acceptance criteria:
  - staff capture current + previous readings per unit
  - system computes consumption (current − previous) and posts a water charge
    using the correct COA code
  - the charge appears as "Other Charges" on the tenant statement
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import UtilityCharge
from apps.payments.statement_service import build_statement
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()


@pytest.fixture
def tenant(db):
    building = Building.objects.create(
        name="Donholm", code="DON", total_floors=1,
        water_rate_per_unit=Decimal("150.00"),
    )
    unit = Unit.objects.create(
        building=building, label="DON1A", monthly_rent=Decimal("12000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Mercy", last_name="Murunga", id_number="M1",
        phone="+254700000001", unit=unit, monthly_rent=Decimal("12000"),
        move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
    )


@pytest.fixture
def client(db):
    user = User.objects.create_user(username="staff", email="s@t.com", password="pw123456!", role="owner")
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.mark.django_db
class TestConsumptionCalculator:
    def test_consumption_times_tariff(self, tenant, client):
        resp = client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 1, "period_year": 2026,
            "opening_reading": "1194", "closing_reading": "1209",
        }, format="json")
        assert resp.status_code == 201
        body = resp.json()
        # 1209 - 1194 = 15 units x KES 150 = 2,250
        assert Decimal(body["units"]) == Decimal("15.00")
        assert Decimal(body["amount"]) == Decimal("2250.00")

    def test_previous_reading_is_carried_forward(self, tenant, client):
        client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 1, "period_year": 2026,
            "opening_reading": "1194", "closing_reading": "1209",
        }, format="json")
        # February: staff enter only the closing reading.
        resp = client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 2, "period_year": 2026,
            "closing_reading": "1220",
        }, format="json")
        assert resp.status_code == 201
        body = resp.json()
        assert Decimal(body["opening_reading"]) == Decimal("1209.00")
        assert Decimal(body["units"]) == Decimal("11.00")
        assert Decimal(body["amount"]) == Decimal("1650.00")

    def test_previous_reading_endpoint_prefills_the_form(self, tenant, client):
        client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 1, "period_year": 2026,
            "opening_reading": "1194", "closing_reading": "1209",
        }, format="json")
        resp = client.get("/api/utility-charges/previous-reading/", {"tenant": tenant.id})
        assert resp.status_code == 200
        assert Decimal(resp.json()["previous_reading"]) == Decimal("1209.00")
        assert Decimal(resp.json()["water_rate_per_unit"]) == Decimal("150.00")

    def test_backwards_meter_is_rejected(self, tenant, client):
        resp = client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 1, "period_year": 2026,
            "opening_reading": "1209", "closing_reading": "1100",
        }, format="json")
        assert resp.status_code == 400
        assert "backwards" in resp.json()["detail"]

    def test_first_reading_without_opening_is_rejected(self, tenant, client):
        resp = client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 1, "period_year": 2026,
            "closing_reading": "1209",
        }, format="json")
        assert resp.status_code == 400
        assert "opening reading" in resp.json()["detail"]

    def test_resubmitting_revises_instead_of_double_billing(self, tenant, client):
        for closing in ("1209", "1210"):
            client.post("/api/utility-charges/reading/", {
                "tenant": tenant.id, "period_month": 1, "period_year": 2026,
                "opening_reading": "1194", "closing_reading": closing,
            }, format="json")
        charges = UtilityCharge.objects.filter(tenant=tenant, period_month=1)
        assert charges.count() == 1
        assert charges.first().closing_reading == Decimal("1210.00")


@pytest.mark.django_db
class TestPostsToLedgerAndStatement:
    def test_charge_posts_to_the_gl_with_the_right_codes(self, tenant, client):
        client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 1, "period_year": 2026,
            "opening_reading": "1194", "closing_reading": "1209",
        }, format="json")
        charge = UtilityCharge.objects.get(tenant=tenant)

        from apps.ledger.models import JournalEntry

        entry = JournalEntry.objects.get(source_type="utility_charge", source_id=charge.pk)
        legs = {line.account.code: (line.debit, line.credit) for line in entry.lines.all()}
        # DR 1040 receivable / CR 4150 utilities reimbursed
        assert legs["1040"] == (Decimal("2250.00"), Decimal("0.00"))
        assert legs["4150"] == (Decimal("0.00"), Decimal("2250.00"))

    def test_description_omits_the_meter_readings(self, tenant, client):
        """Readings are stored and price the charge, but stay off the statement."""
        client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 1, "period_year": 2026,
            "opening_reading": "1194", "closing_reading": "1209",
        }, format="json")
        charge = UtilityCharge.objects.get(tenant=tenant)

        # The readings are still on the record ...
        assert charge.opening_reading == Decimal("1194.00")
        assert charge.closing_reading == Decimal("1209.00")
        # ... but the tenant-facing line is a single row with no dial figures.
        description = charge.description()
        assert "\n" not in description
        assert "Opening Reading" not in description
        assert "Closing Reading" not in description
        assert "(15 Units" in description

    def test_charge_shows_as_other_charges_on_the_statement(self, tenant, client):
        client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 1, "period_year": 2026,
            "opening_reading": "1194", "closing_reading": "1209",
        }, format="json")
        st = build_statement(
            tenant,
            statement_date=_dt.date(2026, 2, 1),
            as_of=_dt.date(2026, 2, 1),
        )
        assert st["other_charges"] == "2,250.00"
        water_rows = [
            r for r in st["rows"] if "Water Usage" in r["description_lines"][0]
        ]
        assert len(water_rows) == 1
        assert "15 Units" in water_rows[0]["description_lines"][0]
