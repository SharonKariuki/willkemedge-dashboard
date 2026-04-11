"""Tests for tenant lifecycle: create, move-in, move-out, document upload."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitStatus

User = get_user_model()


class TenantLifecycleTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="admin", email="admin@test.com", password="testpass123!"
        )
        cls.building = Building.objects.create(name="Block A", total_floors=3)
        cls.unit = Unit.objects.create(
            building=cls.building,
            label="A1",
            monthly_rent=Decimal("15000"),
            status=UnitStatus.VACANT,
        )
        cls.occupied_unit = Unit.objects.create(
            building=cls.building,
            label="A2",
            monthly_rent=Decimal("12000"),
            status=UnitStatus.OCCUPIED_PAID,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        # Reset unit status for each test
        self.unit.status = UnitStatus.VACANT
        self.unit.save(update_fields=["status"])

    def _tenant_payload(self, **overrides):
        base = {
            "first_name": "Jane",
            "last_name": "Wanjiku",
            "id_number": "12345678",
            "phone": "+254712345678",
            "unit": self.unit.id,
            "monthly_rent": "15000.00",
            "move_in_date": "2026-04-01",
        }
        base.update(overrides)
        return base

    # --- Create / move-in -----------------------------------------------

    def test_create_tenant_succeeds_and_moves_in(self):
        resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        assert resp.status_code == status.HTTP_201_CREATED

        # Unit should now be OCCUPIED_UNPAID
        self.unit.refresh_from_db()
        assert self.unit.status == UnitStatus.OCCUPIED_UNPAID

    def test_create_tenant_on_occupied_unit_fails(self):
        resp = self.client.post(
            "/api/tenants/",
            self._tenant_payload(unit=self.occupied_unit.id, id_number="99999999"),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_tenant_duplicate_id_number_fails(self):
        self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        # Second tenant with same id_number
        unit2 = Unit.objects.create(
            building=self.building, label="A3", monthly_rent=Decimal("10000"),
            status=UnitStatus.VACANT,
        )
        resp = self.client.post(
            "/api/tenants/",
            self._tenant_payload(unit=unit2.id),
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # --- List / filter --------------------------------------------------

    def test_list_tenants(self):
        self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        resp = self.client.get("/api/tenants/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_filter_by_status(self):
        self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        resp = self.client.get("/api/tenants/", {"status": "active"})
        assert len(resp.json()) == 1
        resp2 = self.client.get("/api/tenants/", {"status": "moved_out"})
        assert len(resp2.json()) == 0

    # --- Retrieve -------------------------------------------------------

    def test_retrieve_tenant_detail(self):
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]
        resp = self.client.get(f"/api/tenants/{tid}/")
        assert resp.status_code == 200
        assert resp.json()["full_name"] == "Jane Wanjiku"
        assert "documents" in resp.json()

    # --- Move-out -------------------------------------------------------

    def test_move_out_tenant(self):
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]

        resp = self.client.post(
            f"/api/tenants/{tid}/move-out/",
            {"move_out_date": "2026-04-30", "notes": "Unit in good condition."},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "moved_out"

        # Unit should be VACANT again
        self.unit.refresh_from_db()
        assert self.unit.status == UnitStatus.VACANT

    def test_move_out_already_moved_out_fails(self):
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]
        self.client.post(f"/api/tenants/{tid}/move-out/", {}, format="json")

        resp = self.client.post(f"/api/tenants/{tid}/move-out/", {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # --- Document upload ------------------------------------------------

    def test_upload_document(self):
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]

        pdf = SimpleUploadedFile("lease.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        resp = self.client.post(
            f"/api/tenants/{tid}/documents/",
            {"file": pdf, "doc_type": "lease"},
            format="multipart",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["original_name"] == "lease.pdf"

    def test_upload_invalid_file_type(self):
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]

        exe = SimpleUploadedFile("malware.exe", b"MZ fake", content_type="application/x-msdownload")
        resp = self.client.post(
            f"/api/tenants/{tid}/documents/",
            {"file": exe, "doc_type": "other"},
            format="multipart",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_documents(self):
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]

        pdf = SimpleUploadedFile("id.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        self.client.post(
            f"/api/tenants/{tid}/documents/",
            {"file": pdf, "doc_type": "id_front"},
            format="multipart",
        )

        resp = self.client.get(f"/api/tenants/{tid}/documents/list/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    # --- Auth -----------------------------------------------------------

    def test_unauthenticated_denied(self):
        anon = APIClient()
        resp = anon.get("/api/tenants/")
        assert resp.status_code == 401
