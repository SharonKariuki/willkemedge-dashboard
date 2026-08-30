"""
The deposit card's data contract.

The card used to show `deposit_paid` with nothing to hold it against, so a
residential deposit sitting at zero looked no different from one paid in full.
These pin the three derived fields it now reads.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
D = Decimal


class DepositApiTestCase(APITestCase):
    """Shared setup: an authenticated owner and a building to let units in."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="deposits", email="deposits@test.com",
            password="testpass123!", role="owner",
        )
        cls.building = Building.objects.create(name="Wilkem Edge", code="WED", total_floors=2)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _let(self, label, classification, rent, held):
        unit = Unit.objects.create(
            building=self.building, label=label, monthly_rent=D(rent),
            classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name=label, last_name="Tenant", id_number=f"ID-{label}",
            phone=f"+2547111111{len(label):02d}", unit=unit, monthly_rent=D(rent),
            deposit_paid=D(held), move_in_date="2026-07-01", status=TenantStatus.ACTIVE,
        )

    def _detail(self, tenant):
        resp = self.client.get(f"/api/tenants/{tenant.id}/")
        assert resp.status_code == status.HTTP_200_OK, resp.content
        return resp.json()


class DepositCardFieldsTests(DepositApiTestCase):
    def test_residential_expects_one_months_rent(self):
        tenant = self._let("WED01", UnitClassification.RESIDENTIAL, "20000", "20000")

        body = self._detail(tenant)

        assert body["deposit_months"] == 1
        assert Decimal(str(body["expected_deposit"])) == D("20000.00")
        assert Decimal(str(body["deposit_shortfall"])) == D("0.00")

    def test_commercial_still_expects_three_months_rent(self):
        """Matasia Commercial is the exception the one-month rule is against."""
        tenant = self._let("WED02", UnitClassification.BUSINESS, "24000", "72000")

        body = self._detail(tenant)

        assert body["deposit_months"] == 3
        assert Decimal(str(body["expected_deposit"])) == D("72000.00")
        assert Decimal(str(body["deposit_shortfall"])) == D("0.00")

    def test_an_unrecorded_residential_deposit_reports_a_full_shortfall(self):
        tenant = self._let("WED03", UnitClassification.RESIDENTIAL, "18000", "0")

        body = self._detail(tenant)

        assert Decimal(str(body["deposit_shortfall"])) == D("18000.00")
        assert Decimal(str(body["deposit_paid"])) == D("0.00"), "cash received was restated"

    def test_the_endpoint_never_restates_what_was_received(self):
        """Reading the card must not quietly round a deposit up to policy."""
        tenant = self._let("WED04", UnitClassification.RESIDENTIAL, "18000", "5000")

        self._detail(tenant)

        tenant.refresh_from_db()
        assert tenant.deposit_paid == D("5000.00")


class AgreedDepositTests(DepositApiTestCase):
    """Editing the expected deposit by hand.

    Some lettings were agreed at a figure the rule does not produce, and the
    card reported them as short of money nobody owed. The edit form can now set
    what was actually agreed, and clear it again.
    """

    def _edit(self, tenant, **fields):
        resp = self.client.patch(f"/api/tenants/{tenant.id}/", fields, format="json")
        assert resp.status_code == status.HTTP_200_OK, resp.content
        return resp.json()

    def test_setting_it_clears_a_shortfall_nobody_owed(self):
        tenant = self._let("WED10", UnitClassification.RESIDENTIAL, "15000", "14000")
        assert Decimal(str(self._detail(tenant)["deposit_shortfall"])) == D("1000.00")

        self._edit(tenant, agreed_deposit="14000")

        body = self._detail(tenant)
        assert body["deposit_is_agreed"] is True
        assert Decimal(str(body["expected_deposit"])) == D("14000.00")
        assert Decimal(str(body["deposit_shortfall"])) == D("0.00")

    def test_a_blank_box_returns_the_letting_to_the_rule(self):
        """The form sends "" for an empty field; that must clear the override
        rather than 400, and must not read as "agreed at zero"."""
        tenant = self._let("WED11", UnitClassification.RESIDENTIAL, "15000", "14000")
        self._edit(tenant, agreed_deposit="14000")

        self._edit(tenant, agreed_deposit="")

        body = self._detail(tenant)
        assert body["agreed_deposit"] is None
        assert body["deposit_is_agreed"] is False
        assert Decimal(str(body["expected_deposit"])) == D("15000.00")

    def test_an_override_does_not_touch_what_was_received(self):
        tenant = self._let("WED12", UnitClassification.RESIDENTIAL, "15000", "14000")

        self._edit(tenant, agreed_deposit="14000")

        tenant.refresh_from_db()
        assert tenant.deposit_paid == D("14000.00")
        assert tenant.agreed_deposit == D("14000.00")

    def test_a_negative_agreed_deposit_is_rejected(self):
        tenant = self._let("WED13", UnitClassification.RESIDENTIAL, "15000", "14000")

        resp = self.client.patch(
            f"/api/tenants/{tenant.id}/", {"agreed_deposit": "-1"}, format="json",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content

    def test_an_untouched_edit_leaves_the_override_alone(self):
        """Saving the form without the field must not silently clear it."""
        tenant = self._let("WED14", UnitClassification.RESIDENTIAL, "15000", "14000")
        self._edit(tenant, agreed_deposit="14000")

        self._edit(tenant, phone="+254700111222")

        tenant.refresh_from_db()
        assert tenant.agreed_deposit == D("14000.00")
