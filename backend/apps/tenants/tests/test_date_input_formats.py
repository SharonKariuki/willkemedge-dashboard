"""Dates typed the Kenyan way are accepted, and read day-first.

The landlord could not register a tenant starting 01-10-2026: DRF ships
ISO-8601 as its only date format, so the API answered "Date has wrong format.
Use one of these formats instead: YYYY-MM-DD." and the dashboard put that
straight in a toast.

The admin was worse. Its stock "en" locale is month-first, so 01/10/2026 was
not rejected — it was stored as 10 January and would have billed from the
wrong month. A rejected date gets retyped; a silently misread one does not.

Both surfaces now read day-first, with ISO first in each list so the date
picker (which always submits YYYY-MM-DD) and every management command are
untouched.
"""
import datetime as dt
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.tenants.models import Tenant

User = get_user_model()

OCTOBER_FIRST = dt.date(2026, 10, 1)


class TenantCreateDateFormatTests(APITestCase):
    """POST /api/tenants/ — the surface the landlord actually hit."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="owner", email="owner@test.com", password="testpass123!", role="owner"
        )
        cls.building = Building.objects.create(name="Matasia Commercial", code="MC", total_floors=2)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _unit(self, label):
        return Unit.objects.create(
            building=self.building,
            label=label,
            unit_type="shop",
            classification=UnitClassification.BUSINESS,
            monthly_rent=Decimal("15000"),
            status=UnitStatus.VACANT,
        )

    def _payload(self, label, id_number, move_in):
        return {
            "first_name": "Sidai Lonestar",
            "last_name": "Healthcare",
            "id_number": id_number,
            "phone": "+254722301982",
            "unit": self._unit(label).id,
            "monthly_rent": "15000.00",
            "deposit_paid": "0",
            "move_in_date": move_in,
        }

    def test_day_first_move_in_dates_are_accepted_and_read_day_first(self):
        for i, typed in enumerate(["01-10-2026", "01/10/2026", "01.10.2026", "2026-10-01"]):
            with self.subTest(typed=typed):
                resp = self.client.post(
                    "/api/tenants/",
                    self._payload(f"MCG{60 + i}", f"SIDAI-{i}", typed),
                    format="json",
                )
                assert resp.status_code == status.HTTP_201_CREATED, resp.json()
                tenant = Tenant.objects.get(pk=resp.json()["id"])
                assert tenant.move_in_date == OCTOBER_FIRST

    def test_ambiguous_looking_date_is_not_read_as_month_first(self):
        """13-10-2026 can only be 13 October; 10-13-2026 is not a date at all.

        Pins the reading direction: were the list month-first, the first would
        fail and the second would succeed. It is the other way round.
        """
        ok = self.client.post(
            "/api/tenants/", self._payload("MCG71", "SIDAI-OK", "13-10-2026"), format="json"
        )
        assert ok.status_code == status.HTTP_201_CREATED, ok.json()
        assert Tenant.objects.get(pk=ok.json()["id"]).move_in_date == dt.date(2026, 10, 13)

        bad = self.client.post(
            "/api/tenants/", self._payload("MCG72", "SIDAI-BAD", "10-13-2026"), format="json"
        )
        assert bad.status_code == status.HTTP_400_BAD_REQUEST
        assert "move_in_date" in bad.json()

    def test_a_genuinely_malformed_date_is_still_rejected(self):
        resp = self.client.post(
            "/api/tenants/", self._payload("MCG73", "SIDAI-JUNK", "next Tuesday"), format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "move_in_date" in resp.json()


class AdminDateFormatTests(APITestCase):
    """Django's own forms — the admin — parse and print day-first.

    ``config.formats`` is reached through ``FORMAT_MODULE_PATH``; without it
    these fall back to the month-first stock ``en`` locale.
    """

    def test_slash_date_is_read_day_first_not_month_first(self):
        assert forms.DateField().clean("01/10/2026") == OCTOBER_FIRST

    def test_dash_date_is_accepted(self):
        assert forms.DateField().clean("01-10-2026") == OCTOBER_FIRST

    def test_iso_still_wins(self):
        assert forms.DateField().clean("2026-10-01") == OCTOBER_FIRST

    def test_dates_are_printed_with_the_month_spelled(self):
        """A numeric date read off a page is a date someone can re-enter wrongly."""
        from django.utils import formats

        assert formats.date_format(OCTOBER_FIRST) == "01 Oct 2026"
