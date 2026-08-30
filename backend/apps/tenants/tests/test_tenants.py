"""Tests for tenant lifecycle: create, move-in, move-out, document upload."""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitStatus

User = get_user_model()


class TenantLifecycleTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="admin", email="admin@test.com", password="testpass123!", role="owner"
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

    def test_upload_rejects_spoofed_content(self):
        """A payload disguised with a valid MIME + extension but wrong magic
        bytes must be rejected by the content sniff."""
        create_resp = self.client.post("/api/tenants/", self._tenant_payload(), format="json")
        tid = create_resp.json()["id"]

        # Declares image/png + .png, but the bytes are HTML — not a real PNG.
        spoof = SimpleUploadedFile(
            "id.png", b"<html><script>alert(1)</script></html>", content_type="image/png"
        )
        resp = self.client.post(
            f"/api/tenants/{tid}/documents/",
            {"file": spoof, "doc_type": "id_front"},
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
            username="admin", email="admin@test.com", password="testpass123!", role="owner"
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

    def test_list_balance_uses_the_rent_roll_and_preserves_a_credit(self):
        from apps.payments.models import Payment, UtilityCharge

        UtilityCharge.objects.create(
            tenant=self.owing, posting_date=dt.date(2026, 8, 1),
            period_month=8, period_year=2026, label="Water Usage", amount=Decimal("1200"),
        )
        Payment.objects.create(
            tenant=self.owing, amount=Decimal("6750"), payment_date=dt.date(2026, 8, 3),
            # The receipt settles the prior rent arrears, but remains August
            # cash in the rent-roll balance.
            period_month=5, period_year=2026, source="mpesa",
        )

        with patch("apps.tenants.serializers.timezone.localdate", return_value=dt.date(2026, 8, 21)):
            rows = {r["full_name"]: r for r in self.client.get("/api/tenants/").json()}

        assert Decimal(rows["Owing Test"]["balance"]) == Decimal("-550.00")
        # Status remains governed by open rent arrears, not by a credit that
        # happened to arrive after the current charge was raised.
        assert rows["Owing Test"]["payment_status"] == "in_arrears"


class TenantDetailPaymentFieldsTests(APITestCase):
    """The detail page styles arrears and gates its Remind button on
    `payment_status`, and shows `total_paid` beside them. The serializer omitted
    the first (so arrears always rendered as paid) and counted voided receipts
    in the second."""

    @classmethod
    def setUpTestData(cls):
        from apps.payments.models import Arrears, Payment
        from apps.tenants.models import Tenant

        cls.user = User.objects.create_user(
            username="admin", email="admin@test.com", password="testpass123!", role="owner"
        )
        cls.building = Building.objects.create(name="Road Block Eldoret", total_floors=4)
        unit = Unit.objects.create(
            building=cls.building, label="RB305",
            monthly_rent=Decimal("7000"), status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.tenant = Tenant.objects.create(
            first_name="Sheldon", last_name="Mutai", id_number="PENDING-RB305",
            phone="+254707575747", unit=unit,
            monthly_rent=Decimal("7000"), move_in_date="2026-01-01",
        )
        Arrears.objects.create(
            tenant=cls.tenant, period_month=7, period_year=2026,
            expected_rent=Decimal("7000"), amount_paid=Decimal("6000"),
            balance=Decimal("1000"), is_cleared=False,
        )
        Payment.objects.create(
            tenant=cls.tenant, amount=Decimal("6000"), payment_date="2026-08-11",
            period_month=7, period_year=2026, source="mpesa",
        )
        # Reversed receipt — money that never was.
        Payment.objects.create(
            tenant=cls.tenant, amount=Decimal("4000"), payment_date="2026-08-12",
            period_month=7, period_year=2026, source="mpesa",
            voided_at=timezone.now(), void_reason="duplicate capture",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_detail_exposes_payment_status(self):
        body = self.client.get(f"/api/tenants/{self.tenant.pk}/").json()
        assert body["payment_status"] == "in_arrears"
        assert Decimal(body["total_arrears"]) == Decimal("1000.00")

    def test_detail_total_paid_excludes_voided(self):
        body = self.client.get(f"/api/tenants/{self.tenant.pk}/").json()
        assert Decimal(body["total_paid"]) == Decimal("6000.00")

    def test_payment_history_excludes_voided(self):
        body = self.client.get(f"/api/tenants/{self.tenant.pk}/payment-history/").json()
        assert Decimal(body["total_paid"]) == Decimal("6000.00")
        assert [Decimal(p["amount"]) for p in body["payments"]] == [Decimal("6000.00")]


class TenantClassificationExposureTests(APITestCase):
    """The detail page drops the rent-security-deposit card and shows a VAT
    column for commercial lettings, so it has to be able to tell them apart."""

    @classmethod
    def setUpTestData(cls):
        from apps.buildings.models import UnitClassification
        from apps.tenants.models import Tenant

        cls.user = User.objects.create_user(
            username="cls-admin", email="cls@test.com", password="testpass123!", role="owner"
        )
        building = Building.objects.create(name="Matasia Arcade", total_floors=2)

        def let(label, classification, care_of=""):
            unit = Unit.objects.create(
                building=building, label=label, monthly_rent=Decimal("24000"),
                classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
            )
            return Tenant.objects.create(
                first_name=label, last_name="Ltd", id_number=f"CLS-{label}",
                phone="+254700000003", unit=unit, monthly_rent=Decimal("24000"),
                care_of=care_of, move_in_date="2026-07-01",
            )

        cls.commercial = let("MCX01", UnitClassification.BUSINESS, care_of="Dennis Kerosi")
        cls.residential = let("MRX01", UnitClassification.RESIDENTIAL)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_commercial_letting_reports_business(self):
        body = self.client.get(f"/api/tenants/{self.commercial.pk}/").json()
        assert body["unit_classification"] == "BUSINESS"

    def test_residential_letting_reports_residential(self):
        body = self.client.get(f"/api/tenants/{self.residential.pk}/").json()
        assert body["unit_classification"] == "RESIDENTIAL"

    def test_contact_person_is_exposed_for_the_contact_card(self):
        body = self.client.get(f"/api/tenants/{self.commercial.pk}/").json()
        assert body["care_of"] == "Dennis Kerosi"
