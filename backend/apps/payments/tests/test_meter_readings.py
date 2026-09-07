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


@pytest.mark.django_db
class TestTheChainStaysContinuous:
    """A meter's history is a chain: each month opens where the last one closed.

    Every test here is a way the chain used to break — each one billing a tenant
    for water nobody metered, or letting water through unbilled.
    """

    def _read(self, client, tenant, month, closing, **extra):
        return client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": month, "period_year": 2026,
            "closing_reading": closing, **extra,
        }, format="json")

    def test_backfilled_month_opens_on_the_month_before_it(self, tenant, client):
        """Not on the newest reading on file, which is a *later* month."""
        self._read(client, tenant, 1, "1209", opening_reading="1194")
        self._read(client, tenant, 3, "1240")  # March, entered before February

        resp = self._read(client, tenant, 2, "1220")

        assert resp.status_code == 201, resp.json()
        assert Decimal(resp.json()["opening_reading"]) == Decimal("1209.00")
        assert Decimal(resp.json()["units"]) == Decimal("11.00")

    def test_backfilling_re_derives_the_months_after_it(self, tenant, client):
        """March was billed off January; once February lands, March must move."""
        self._read(client, tenant, 1, "1209", opening_reading="1194")
        self._read(client, tenant, 3, "1240")
        assert UtilityCharge.objects.get(tenant=tenant, period_month=3).units == Decimal("31.00")

        self._read(client, tenant, 2, "1220")

        march = UtilityCharge.objects.get(tenant=tenant, period_month=3)
        assert march.opening_reading == Decimal("1220.00")
        assert march.units == Decimal("20.00")
        assert march.amount == Decimal("3000.00")  # 20 x 150

    def test_correcting_a_reading_carries_forward(self, tenant, client):
        self._read(client, tenant, 1, "1209", opening_reading="1194")
        self._read(client, tenant, 2, "1220")

        # January's closing was misread: it was 1214, not 1209.
        self._read(client, tenant, 1, "1214", opening_reading="1194")

        february = UtilityCharge.objects.get(tenant=tenant, period_month=2)
        assert february.opening_reading == Decimal("1214.00")
        assert february.units == Decimal("6.00")
        assert february.amount == Decimal("900.00")

    def test_the_gl_follows_the_carried_correction(self, tenant, client):
        from apps.ledger.models import JournalEntry

        self._read(client, tenant, 1, "1209", opening_reading="1194")
        self._read(client, tenant, 2, "1220")
        self._read(client, tenant, 1, "1214", opening_reading="1194")

        february = UtilityCharge.objects.get(tenant=tenant, period_month=2)
        entry = JournalEntry.objects.get(source_type="utility_charge", source_id=february.pk)
        legs = {line.account.code: (line.debit, line.credit) for line in entry.lines.all()}
        assert legs["1040"] == (Decimal("900.00"), Decimal("0.00"))
        assert legs["4150"] == (Decimal("0.00"), Decimal("900.00"))

    def test_re_derived_months_keep_the_tariff_they_were_billed_at(self, tenant, client):
        """A correction restates consumption, never the price history."""
        self._read(client, tenant, 1, "1209", opening_reading="1194")
        self._read(client, tenant, 2, "1220")  # 11 units @ 150

        building = tenant.unit.building
        building.water_rate_per_unit = Decimal("200.00")
        building.save(update_fields=["water_rate_per_unit"])

        self._read(client, tenant, 1, "1214", opening_reading="1194")

        february = UtilityCharge.objects.get(tenant=tenant, period_month=2)
        assert february.units == Decimal("6.00")
        assert february.amount == Decimal("900.00")  # 6 x 150, the rate it was billed at

    def test_opening_that_contradicts_the_meter_is_rejected(self, tenant, client):
        self._read(client, tenant, 1, "1209", opening_reading="1194")

        resp = self._read(client, tenant, 2, "1230", opening_reading="1215")

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "1215" in detail and "1209" in detail

    def test_a_replaced_meter_may_restart_the_dial(self, tenant, client):
        self._read(client, tenant, 1, "1209", opening_reading="1194")

        resp = self._read(
            client, tenant, 2, "30", opening_reading="0", meter_replaced=True
        )

        assert resp.status_code == 201, resp.json()
        assert Decimal(resp.json()["units"]) == Decimal("30.00")

    def test_the_meter_belongs_to_the_unit_not_the_tenant(self, tenant, client):
        """The dial does not reset when someone moves out."""
        self._read(client, tenant, 1, "1209", opening_reading="1194")
        tenant.status = TenantStatus.MOVED_OUT
        tenant.save(update_fields=["status"])
        incoming = Tenant.objects.create(
            first_name="Peter", last_name="Otieno", id_number="P1",
            phone="+254700000002", unit=tenant.unit, monthly_rent=Decimal("12000"),
            move_in_date="2026-02-01", status=TenantStatus.ACTIVE,
        )

        resp = self._read(client, incoming, 2, "1220")

        assert resp.status_code == 201, resp.json()
        assert Decimal(resp.json()["opening_reading"]) == Decimal("1209.00")
        assert Decimal(resp.json()["units"]) == Decimal("11.00")

    def test_previous_reading_endpoint_answers_for_the_period_asked(self, tenant, client):
        self._read(client, tenant, 1, "1209", opening_reading="1194")
        self._read(client, tenant, 3, "1240")

        resp = client.get("/api/utility-charges/previous-reading/", {
            "tenant": tenant.id, "month": 2, "year": 2026,
        })

        assert resp.status_code == 200
        assert Decimal(resp.json()["previous_reading"]) == Decimal("1209.00")


@pytest.mark.django_db
class TestAuditCommand:
    def test_it_finds_and_repairs_a_broken_chain(self, tenant, client):
        from io import StringIO

        from django.core.management import call_command

        client.post("/api/utility-charges/reading/", {
            "tenant": tenant.id, "period_month": 1, "period_year": 2026,
            "opening_reading": "1194", "closing_reading": "1209",
        }, format="json")
        # A charge as the importer could leave it: readings that do not chain,
        # and units/value that do not agree with them.
        UtilityCharge.objects.create(
            tenant=tenant, posting_date=_dt.date(2026, 2, 28),
            period_month=2, period_year=2026, label="Water Usage",
            opening_reading=Decimal("1200"), closing_reading=Decimal("1220"),
            units=Decimal("20"), amount=Decimal("3000"),
        )

        out = StringIO()
        call_command("audit_water_readings", "--unit", "DON1A", stdout=out)
        report = out.getvalue()
        assert "1 with problems" in report
        assert "opens at 1,200 but 01/2026 closed at 1,209" in report
        # Report-only: nothing moved.
        assert UtilityCharge.objects.get(tenant=tenant, period_month=2).units == Decimal("20.00")

        out = StringIO()
        call_command("audit_water_readings", "--unit", "DON1A", "--apply", stdout=out)
        february = UtilityCharge.objects.get(tenant=tenant, period_month=2)
        assert february.opening_reading == Decimal("1209.00")
        assert february.units == Decimal("11.00")
        assert february.amount == Decimal("1650.00")  # 11 x 150, its own billed rate
