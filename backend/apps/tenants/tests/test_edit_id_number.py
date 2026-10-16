"""An edited ID number has to hold everywhere the tenant is looked up.

Everything that belongs to a tenant — payments, arrears, ledger lines,
credits, documents — hangs off the row's primary key, so an edit to
``id_number`` carries through to all of it without a copy to keep in step.
What did not hold was the two seeds that found their tenants *by* the ID:
once the owner replaced a ``RES-``/``BIZ-`` placeholder, a re-run no longer
recognised the tenant and seeded a second one onto the same unit.
"""
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Payment
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()


def _rows(response):
    return response.data if isinstance(response.data, list) else response.data["results"]


class EditedIdNumberTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="owner", email="owner@test.com",
            password="testpass123!", role="owner",
        )
        building = Building.objects.create(name="Wilkem Edge", code="WED", total_floors=1)
        unit = Unit.objects.create(
            building=building, label="WEDA01", monthly_rent=Decimal("10000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.tenant = Tenant.objects.create(
            first_name="Jane", last_name="Wanjiru", id_number="PENDING-WEDA01",
            phone="+254711111111", unit=unit, monthly_rent=Decimal("10000"),
            move_in_date="2026-07-01", status=TenantStatus.ACTIVE,
        )
        Payment.objects.create(
            tenant=cls.tenant, amount=Decimal("10000"), payment_date="2026-07-05",
            period_month=7, period_year=2026, reference="TEST123",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _set_id(self, value):
        response = self.client.patch(
            f"/api/tenants/{self.tenant.id}/", {"id_number": value}, format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        self.tenant.refresh_from_db()

    def test_the_new_id_is_what_the_tenant_page_shows(self):
        self._set_id("12345678")

        response = self.client.get(f"/api/tenants/{self.tenant.id}/")

        assert response.data["id_number"] == "12345678"

    def test_search_finds_the_new_id_and_not_the_old_one(self):
        self._set_id("12345678")

        found = _rows(self.client.get("/api/tenants/?search=12345678"))
        stale = _rows(self.client.get("/api/tenants/?search=PENDING-WEDA01"))

        assert [r["id"] for r in found] == [self.tenant.id]
        assert stale == []

    def test_the_tenants_payments_stay_with_them(self):
        self._set_id("12345678")

        assert Payment.objects.filter(tenant__id_number="12345678").count() == 1
        response = self.client.get(f"/api/tenants/{self.tenant.id}/")
        assert Decimal(response.data["total_paid"]) == Decimal("10000.00")


class SeedsRespectAnEditedIdTests(APITestCase):
    """Re-running a seed after an ID edit must not duplicate the tenant."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="owner", email="owner@test.com",
            password="testpass123!", role="owner",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _rerun_after_editing(self, command, placeholder):
        call_command(command, stdout=StringIO())
        tenant = Tenant.objects.get(id_number=placeholder)
        response = self.client.patch(
            f"/api/tenants/{tenant.id}/", {"id_number": "EDITED-1"}, format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        before = Tenant.objects.count()

        call_command(command, stdout=StringIO())

        assert Tenant.objects.count() == before
        assert Tenant.objects.filter(unit=tenant.unit).count() == 1
        assert Tenant.objects.get(pk=tenant.pk).id_number == "EDITED-1"

    def test_seed_wilkem_property(self):
        self._rerun_after_editing("seed_wilkem_property", "BIZ-G01")

    def test_seed_wilkem_rentals(self):
        call_command("seed_wilkem_rentals", stdout=StringIO())
        placeholder = Tenant.objects.filter(id_number__startswith="RES-").values_list(
            "id_number", flat=True,
        ).first() or Tenant.objects.values_list("id_number", flat=True).first()
        self._rerun_after_editing("seed_wilkem_rentals", placeholder)
