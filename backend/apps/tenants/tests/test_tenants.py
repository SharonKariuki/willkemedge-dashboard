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

    # --- Rent due day (Feature 8: rent-due-date capture) ----------------

    def test_create_tenant_persists_due_day(self):
        resp = self.client.post(
            "/api/tenants/", self._tenant_payload(due_day=12), format="json"
        )
        assert resp.status_code == status.HTTP_201_CREATED
        tid = resp.json()["id"]
        # Round-trips from the DB on retrieve → persisted, and available to the
        # reminder scheduler (which builds the due date from due_day).
        assert self.client.get(f"/api/tenants/{tid}/").json()["due_day"] == 12

    def test_due_day_defaults_to_5_when_omitted(self):
        resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert self.client.get(f"/api/tenants/{resp.json()['id']}/").json()["due_day"] == 5

    def test_update_due_day(self):
        tid = self.client.post(
            "/api/tenants/", self._tenant_payload(), format="json"
        ).json()["id"]
        resp = self.client.patch(f"/api/tenants/{tid}/", {"due_day": 20}, format="json")
        assert resp.status_code == 200
        assert self.client.get(f"/api/tenants/{tid}/").json()["due_day"] == 20

    def test_due_day_out_of_range_rejected(self):
        resp = self.client.post(
            "/api/tenants/", self._tenant_payload(due_day=40), format="json"
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

    def test_upload_sanitizes_traversal_filename(self):
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]

        evil = SimpleUploadedFile(
            "../../etc/passwd.pdf", b"%PDF-1.4 fake", content_type="application/pdf"
        )
        resp = self.client.post(
            f"/api/tenants/{tid}/documents/",
            {"file": evil, "doc_type": "other"},
            format="multipart",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        name = resp.json()["original_name"]
        # No path components survive.
        assert "/" not in name and "\\" not in name and ".." not in name
        assert name == "passwd.pdf"

    def test_upload_rejects_disallowed_extension(self):
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]

        # Disguised content-type would pass the MIME check but the extension
        # allowlist must still reject it.
        sneaky = SimpleUploadedFile(
            "shell.sh", b"%PDF-1.4 fake", content_type="application/pdf"
        )
        resp = self.client.post(
            f"/api/tenants/{tid}/documents/",
            {"file": sneaky, "doc_type": "other"},
            format="multipart",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_authenticated_document_download(self):
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]
        pdf = SimpleUploadedFile("lease.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        up = self.client.post(
            f"/api/tenants/{tid}/documents/",
            {"file": pdf, "doc_type": "lease"},
            format="multipart",
        )
        doc_id = up.json()["id"]

        resp = self.client.get(f"/api/tenants/{tid}/documents/{doc_id}/download/")
        assert resp.status_code == 200
        assert resp["Content-Disposition"].startswith("attachment")
        content = b"".join(resp.streaming_content)
        assert content == b"%PDF-1.4 fake"

    def test_document_download_requires_auth(self):
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]
        pdf = SimpleUploadedFile("lease.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        up = self.client.post(
            f"/api/tenants/{tid}/documents/",
            {"file": pdf, "doc_type": "lease"},
            format="multipart",
        )
        doc_id = up.json()["id"]

        anon = APIClient()
        resp = anon.get(f"/api/tenants/{tid}/documents/{doc_id}/download/")
        assert resp.status_code == 401

    # --- Auth -----------------------------------------------------------

    def test_unauthenticated_denied(self):
        anon = APIClient()
        resp = anon.get("/api/tenants/")
        assert resp.status_code == 401


class TenantArrearsFilterExportTests(APITestCase):
    """Feature 9: paid/arrears filter toggle + CSV export."""

    @classmethod
    def setUpTestData(cls):
        from apps.payments.models import Arrears
        from apps.tenants.models import Tenant

        cls.user = User.objects.create_user(
            username="admin", email="admin@test.com", password="testpass123!"
        )
        cls.building = Building.objects.create(name="Block B", total_floors=2)

        def _tenant(label, first, rent):
            unit = Unit.objects.create(
                building=cls.building, label=label,
                monthly_rent=Decimal(rent), status=UnitStatus.OCCUPIED_UNPAID,
            )
            return Tenant.objects.create(
                first_name=first, last_name="Test", id_number=f"ID{label}",
                phone=f"+25470000{label[-1]}", unit=unit,
                monthly_rent=Decimal(rent), move_in_date="2026-04-01",
            )

        # In arrears: uncleared balance of 5000
        cls.owing = _tenant("B1", "Owing", "15000")
        Arrears.objects.create(
            tenant=cls.owing, period_month=5, period_year=2026,
            expected_rent=Decimal("15000"), amount_paid=Decimal("10000"),
            balance=Decimal("5000"), is_cleared=False,
        )
        # Paid up: an arrears row that is fully cleared (balance ignored)
        cls.paid = _tenant("B2", "Paidup", "12000")
        Arrears.objects.create(
            tenant=cls.paid, period_month=5, period_year=2026,
            expected_rent=Decimal("12000"), amount_paid=Decimal("12000"),
            balance=Decimal("0"), is_cleared=True,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_list_exposes_balance_and_payment_status(self):
        rows = {r["full_name"]: r for r in self.client.get("/api/tenants/").json()}
        assert rows["Owing Test"]["payment_status"] == "in_arrears"
        assert Decimal(rows["Owing Test"]["balance"]) == Decimal("5000.00")
        assert rows["Paidup Test"]["payment_status"] == "paid"
        assert Decimal(rows["Paidup Test"]["balance"]) == Decimal("0.00")

    def test_filter_in_arrears(self):
        resp = self.client.get("/api/tenants/", {"payment_status": "in_arrears"})
        names = [r["full_name"] for r in resp.json()]
        assert names == ["Owing Test"]

    def test_filter_paid(self):
        resp = self.client.get("/api/tenants/", {"payment_status": "paid"})
        names = [r["full_name"] for r in resp.json()]
        assert names == ["Paidup Test"]

    def test_csv_export_all(self):
        resp = self.client.get("/api/tenants/export/")
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/csv")
        assert "attachment" in resp["Content-Disposition"]
        body = resp.content.decode()
        assert "Tenant,Building,Unit,Balance,Payment Status,Status" in body
        assert "Owing Test" in body and "In Arrears" in body
        assert "Paidup Test" in body and "Paid" in body

    def test_csv_export_honors_filter(self):
        resp = self.client.get("/api/tenants/export/", {"payment_status": "in_arrears"})
        body = resp.content.decode()
        assert "Owing Test" in body
        assert "Paidup Test" not in body
