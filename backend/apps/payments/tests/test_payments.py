"""Payment processing tests: full, partial, overpayment, arrears, unit status."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import Arrears, Payment
from apps.payments.services import process_payment
from apps.tenants.models import Tenant

User = get_user_model()


class PaymentProcessingTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="admin", email="admin@test.com", password="testpass123!"
        )
        cls.building = Building.objects.create(name="Pay Block", total_floors=2)
        cls.unit = Unit.objects.create(
            building=cls.building,
            label="P1",
            monthly_rent=Decimal("10000"),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.tenant = Tenant.objects.create(
            first_name="John",
            last_name="Doe",
            id_number="PAY001",
            phone="+254700000001",
            unit=cls.unit,
            monthly_rent=Decimal("10000"),
            move_in_date="2026-01-01",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        # Reset unit status
        self.unit.status = UnitStatus.OCCUPIED_UNPAID
        self.unit.save(update_fields=["status"])
        # Clear payments and arrears
        Payment.objects.filter(tenant=self.tenant).delete()
        Arrears.objects.filter(tenant=self.tenant).delete()

    def _now(self):
        now = timezone.now()
        return now.month, now.year

    # --- Service-level tests -------------------------------------------

    def test_full_payment_clears_arrears_and_sets_paid(self):
        month, year = self._now()
        process_payment(
            tenant=self.tenant,
            amount=Decimal("10000"),
            payment_date=timezone.now().date(),
            period_month=month,
            period_year=year,
        )
        arrears = Arrears.objects.get(tenant=self.tenant, period_month=month, period_year=year)
        assert arrears.is_cleared
        assert arrears.balance == Decimal("0")

        self.unit.refresh_from_db()
        assert self.unit.status == UnitStatus.OCCUPIED_PAID

    def test_partial_payment_creates_arrears_balance(self):
        month, year = self._now()
        process_payment(
            tenant=self.tenant,
            amount=Decimal("4000"),
            payment_date=timezone.now().date(),
            period_month=month,
            period_year=year,
        )
        arrears = Arrears.objects.get(tenant=self.tenant, period_month=month, period_year=year)
        assert not arrears.is_cleared
        assert arrears.balance == Decimal("6000")

        self.unit.refresh_from_db()
        assert self.unit.status == UnitStatus.OCCUPIED_PARTIAL

    def test_multiple_partial_payments_accumulate(self):
        month, year = self._now()
        process_payment(
            tenant=self.tenant,
            amount=Decimal("3000"),
            payment_date=timezone.now().date(),
            period_month=month,
            period_year=year,
        )
        process_payment(
            tenant=self.tenant,
            amount=Decimal("7000"),
            payment_date=timezone.now().date(),
            period_month=month,
            period_year=year,
        )
        arrears = Arrears.objects.get(tenant=self.tenant, period_month=month, period_year=year)
        assert arrears.is_cleared
        assert arrears.amount_paid == Decimal("10000")

        self.unit.refresh_from_db()
        assert self.unit.status == UnitStatus.OCCUPIED_PAID

    def test_overpayment_still_clears(self):
        month, year = self._now()
        process_payment(
            tenant=self.tenant,
            amount=Decimal("15000"),
            payment_date=timezone.now().date(),
            period_month=month,
            period_year=year,
        )
        arrears = Arrears.objects.get(tenant=self.tenant, period_month=month, period_year=year)
        assert arrears.is_cleared
        assert arrears.balance == Decimal("0")
        assert arrears.amount_paid == Decimal("15000")

    # --- API-level tests -----------------------------------------------

    def test_create_payment_via_api(self):
        month, year = self._now()
        resp = self.client.post("/api/payments/", {
            "tenant": self.tenant.id,
            "amount": "10000.00",
            "payment_date": timezone.now().date().isoformat(),
            "period_month": month,
            "period_year": year,
            "source": "cash",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED

    def test_recent_payments(self):
        month, year = self._now()
        process_payment(
            tenant=self.tenant,
            amount=Decimal("5000"),
            payment_date=timezone.now().date(),
            period_month=month,
            period_year=year,
        )
        resp = self.client.get("/api/payments/recent/")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_collection_progress(self):
        month, year = self._now()
        resp = self.client.get("/api/payments/collection-progress/", {
            "month": month, "year": year,
        })
        assert resp.status_code == 200
        assert "percentage" in resp.json()

    def test_arrears_list(self):
        month, year = self._now()
        process_payment(
            tenant=self.tenant,
            amount=Decimal("5000"),
            payment_date=timezone.now().date(),
            period_month=month,
            period_year=year,
        )
        resp = self.client.get("/api/arrears/", {"cleared": "false"})
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_filter_payments_by_source(self):
        month, year = self._now()
        process_payment(
            tenant=self.tenant,
            amount=Decimal("5000"),
            payment_date=timezone.now().date(),
            period_month=month,
            period_year=year,
            source="mpesa",
            reference="ABC123",
        )
        resp = self.client.get("/api/payments/", {"source": "mpesa"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_negative_amount_rejected(self):
        month, year = self._now()
        resp = self.client.post("/api/payments/", {
            "tenant": self.tenant.id,
            "amount": "-500",
            "payment_date": timezone.now().date().isoformat(),
            "period_month": month,
            "period_year": year,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_unauthenticated_denied(self):
        anon = APIClient()
        resp = anon.get("/api/payments/")
        assert resp.status_code == 401
