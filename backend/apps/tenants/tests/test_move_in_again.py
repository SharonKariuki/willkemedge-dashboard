"""A moved-out tenant moving in again — same unit, same block, or another property.

Every scenario must leave the old tenancy exactly as it was moved out and put
the new one on a new row, because the old row's payments, arrears and
statement belong to the unit and dates it records.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Payment, PaymentType
from apps.tenants.models import KycStatus, Tenant, TenantDocument, TenantStatus

User = get_user_model()


class MoveInAgainTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="owner", email="owner@test.com", password="testpass123!", role="owner"
        )
        cls.block_a = Building.objects.create(name="Block A", total_floors=2)
        cls.block_b = Building.objects.create(name="Block B", total_floors=2)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.a1 = self._unit(self.block_a, "A1", "15000")
        self.a2 = self._unit(self.block_a, "A2", "12000")
        self.b1 = self._unit(self.block_b, "B1", "20000")

        resp = self.client.post("/api/tenants/", {
            "first_name": "Jane", "last_name": "Wanjiku", "id_number": "12345678",
            "kra_pin": "A007523148T", "phone": "+254712345678", "email": "jane@example.com",
            "unit": self.a1.id, "monthly_rent": "15000.00", "move_in_date": "2026-01-01",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        self.old = Tenant.objects.get(pk=resp.json()["id"])
        TenantDocument.objects.create(
            tenant=self.old, doc_type="id_front", file="tenant_docs/x/id.png",
            original_name="id.png",
        )
        self.old.mark_kyc_verified(self.user)

        resp = self.client.post(
            f"/api/tenants/{self.old.pk}/move-out/",
            {"move_out_date": "2026-06-30", "notes": "Left for Mombasa."}, format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        self.old.refresh_from_db()

    def _unit(self, building, label, rent):
        return Unit.objects.create(
            building=building, label=label, monthly_rent=Decimal(rent),
            status=UnitStatus.VACANT,
        )

    def _move_in(self, unit, **extra):
        body = {"unit": unit.id, "monthly_rent": str(unit.monthly_rent), "move_in_date": "2026-09-01"}
        body.update(extra)
        return self.client.post(f"/api/tenants/{self.old.pk}/move-in/", body, format="json")

    def _assert_new_tenancy(self, resp, unit):
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        new = Tenant.objects.get(pk=resp.json()["id"])
        assert new.pk != self.old.pk
        assert new.unit_id == unit.id
        assert new.status == TenantStatus.ACTIVE
        assert str(new.move_in_date) == "2026-09-01"
        assert new.move_out_date is None
        assert (new.first_name, new.id_number, new.phone) == ("Jane", "12345678", "+254712345678")
        unit.refresh_from_db()
        assert unit.status == UnitStatus.OCCUPIED_UNPAID

        # The old tenancy is untouched history.
        old = Tenant.objects.get(pk=self.old.pk)
        assert old.status == TenantStatus.MOVED_OUT
        assert old.unit_id == self.a1.id
        assert str(old.move_in_date) == "2026-01-01"
        assert str(old.move_out_date) == "2026-06-30"
        assert old.move_out_notes == "Left for Mombasa."
        return new

    # --- The three scenarios --------------------------------------------

    def test_move_back_into_the_same_unit(self):
        self._assert_new_tenancy(self._move_in(self.a1), self.a1)

    def test_move_into_another_unit_in_the_same_building(self):
        self._assert_new_tenancy(self._move_in(self.a2), self.a2)
        self.a1.refresh_from_db()
        assert self.a1.status == UnitStatus.VACANT

    def test_move_into_a_unit_in_another_building(self):
        new = self._assert_new_tenancy(self._move_in(self.b1), self.b1)
        assert new.unit.building_id == self.block_b.id
        assert new.monthly_rent == Decimal("20000")

    # --- What is carried over and booked --------------------------------

    def test_kyc_and_documents_carry_over(self):
        new = self._assert_new_tenancy(self._move_in(self.a2), self.a2)
        assert new.kyc_status == KycStatus.VERIFIED
        assert new.kra_pin == "A007523148T"
        docs = list(new.documents.all())
        assert [d.file.name for d in docs] == ["tenant_docs/x/id.png"]
        # The old tenancy keeps its own document row.
        assert self.old.documents.count() == 1

    def test_deposit_is_booked_on_the_new_tenancy(self):
        new = self._assert_new_tenancy(
            self._move_in(self.b1, deposit_paid="20000.00", deposit_reference="QWE123"),
            self.b1,
        )
        deposit = Payment.objects.get(tenant=new, payment_type=PaymentType.DEPOSIT)
        assert deposit.amount == Decimal("20000.00")
        assert deposit.reference == "QWE123"

    def test_detail_lists_every_tenancy_of_the_person(self):
        new = self._assert_new_tenancy(self._move_in(self.b1), self.b1)
        for pk in (self.old.pk, new.pk):
            tenancies = self.client.get(f"/api/tenants/{pk}/").json()["tenancies"]
            assert [t["id"] for t in tenancies] == [self.old.pk, new.pk]
            assert [t["status"] for t in tenancies] == ["moved_out", "active"]

    def test_plain_registration_with_a_moved_out_id_is_allowed(self):
        resp = self.client.post("/api/tenants/", {
            "first_name": "Jane", "last_name": "Wanjiku", "id_number": "12345678",
            "phone": "+254712345678", "unit": self.a2.id,
            "monthly_rent": "12000.00", "move_in_date": "2026-09-01",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.content

    # --- Refusals -------------------------------------------------------

    def test_occupied_unit_is_refused(self):
        self.a2.status = UnitStatus.OCCUPIED_PAID
        self.a2.save(update_fields=["status"])
        resp = self._move_in(self.a2)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "unit" in resp.json()
        assert Tenant.objects.filter(id_number="12345678").count() == 1

    def test_active_tenant_cannot_move_in_again(self):
        new = self._assert_new_tenancy(self._move_in(self.a2), self.a2)
        resp = self.client.post(
            f"/api/tenants/{new.pk}/move-in/",
            {"unit": self.b1.id, "monthly_rent": "20000", "move_in_date": "2026-09-01"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_only_one_current_tenancy_per_person(self):
        self._assert_new_tenancy(self._move_in(self.a2), self.a2)
        # Again from the old, moved-out row: the person already lives in A2.
        resp = self._move_in(self.b1)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "A2" in resp.json()["detail"]
        self.b1.refresh_from_db()
        assert self.b1.status == UnitStatus.VACANT

    def test_move_in_before_the_move_out_is_refused(self):
        resp = self._move_in(self.a2, move_in_date="2026-06-01")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "move_in_date" in resp.json()
        self.a2.refresh_from_db()
        assert self.a2.status == UnitStatus.VACANT

    def test_two_current_tenancies_with_one_id_are_still_refused(self):
        self._assert_new_tenancy(self._move_in(self.a2), self.a2)
        resp = self.client.post("/api/tenants/", {
            "first_name": "Jane", "last_name": "Wanjiku", "id_number": "12345678",
            "phone": "+254712345678", "unit": self.b1.id,
            "monthly_rent": "20000.00", "move_in_date": "2026-09-01",
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "id_number" in resp.json()
