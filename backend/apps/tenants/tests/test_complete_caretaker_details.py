"""The owner must be able to finish a caretaker's record from the dashboard.

``seed_caretaker_units`` creates each caretaker with a placeholder identity —
``PENDING-<unit>`` and no phone number — because ``id_number`` is unique and
required, and the real details are not to hand when the properties are seeded.
Names and phone were already editable; ``id_number`` was not, so replacing a
placeholder meant a shell on the production box.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, PropertyType
from apps.tenants.models import Tenant

User = get_user_model()


class CompleteCaretakerDetailsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="owner", email="owner@test.com",
            password="testpass123!", role="owner",
        )
        Building.objects.create(
            code="FNN", name="Wilkem Farm, Nyariacho Nyamira",
            property_type=PropertyType.FARM,
        )
        Building.objects.create(
            code="KN", name="Wilkem Residence, The Baobab Karen",
            property_type=PropertyType.EXPENSE_ONLY,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        call_command("seed_caretaker_units", stdout=StringIO(), stderr=StringIO())
        self.caretaker = Tenant.objects.get(unit__label="FNNCH")

    def _patch(self, **fields):
        return self.client.patch(
            f"/api/tenants/{self.caretaker.id}/", fields, format="json",
        )

    def test_the_seeded_caretaker_starts_as_a_placeholder(self):
        assert self.caretaker.id_number == "PENDING-FNNCH"
        assert self.caretaker.phone == ""

    def test_the_owner_can_fill_in_the_real_details(self):
        response = self._patch(
            first_name="Joseph", last_name="Kiplagat",
            id_number="12345678", phone="+254712345678",
        )
        assert response.status_code == status.HTTP_200_OK, response.data

        self.caretaker.refresh_from_db()
        assert self.caretaker.full_name == "Joseph Kiplagat"
        assert self.caretaker.id_number == "12345678"
        assert self.caretaker.phone == "+254712345678"

    def test_filling_the_details_in_does_not_start_charging_them_rent(self):
        """Completing the record is not the same as converting it to a letting."""
        self._patch(id_number="12345678", phone="+254712345678")

        self.caretaker.refresh_from_db()
        assert self.caretaker.is_billable is False
        assert self.caretaker.monthly_rent == 0

    def test_an_id_already_on_another_tenant_is_refused(self):
        other = Tenant.objects.get(unit__label="KNCH")
        other.id_number = "12345678"
        other.save(update_fields=["id_number"])

        response = self._patch(id_number="12345678")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "id_number" in response.data
        self.caretaker.refresh_from_db()
        assert self.caretaker.id_number == "PENDING-FNNCH"

    def test_a_tenant_keeps_their_own_id_on_an_unrelated_edit(self):
        """The uniqueness check must exclude the row being edited."""
        self._patch(id_number="12345678")

        response = self._patch(id_number="12345678", phone="+254700000000")

        assert response.status_code == status.HTTP_200_OK, response.data

    def test_a_blank_id_is_refused(self):
        response = self._patch(id_number="   ")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "id_number" in response.data

    def test_surrounding_whitespace_is_trimmed(self):
        self._patch(id_number="  12345678  ")

        self.caretaker.refresh_from_db()
        assert self.caretaker.id_number == "12345678"

    def test_placeholders_are_findable_by_searching_for_them(self):
        """How the owner locates the records still waiting to be completed."""
        response = self.client.get("/api/tenants/?search=PENDING-")

        assert response.status_code == status.HTTP_200_OK
        rows = response.data if isinstance(response.data, list) else response.data["results"]
        assert {r["full_name"] for r in rows} == {
            t.full_name for t in Tenant.objects.filter(id_number__startswith="PENDING-")
        }
