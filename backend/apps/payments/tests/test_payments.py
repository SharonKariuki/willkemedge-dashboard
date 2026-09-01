"""Payment processing tests: full, partial, overpayment, arrears, unit status."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.models import Arrears, Payment, Transaction
from apps.payments.services import process_payment
from apps.payments.tax_service import split_tax_inclusive
from apps.tenants.models import Tenant

User = get_user_model()


class PaymentProcessingTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="admin", email="admin@test.com", password="testpass123!", role="owner"
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
        """The current period, in the project timezone.

        Not `timezone.now()`: that is UTC, and Nairobi is three hours ahead, so
        between midnight and 03:00 EAT it names the previous month. The status
        rules read `timezone.localdate()`, so a payment booked against the UTC
        month looks like an unsettled *earlier* month to them and the unit lands
        in ARREARS instead of PARTIAL.
        """
        today = timezone.localdate()
        return today.month, today.year

    # --- Service-level tests -------------------------------------------

    def test_full_payment_clears_arrears_and_sets_paid(self):
        month, year = self._now()
        process_payment(
            tenant=self.tenant,
            amount=Decimal("10000"),
            payment_date=timezone.localdate(),
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
            payment_date=timezone.localdate(),
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
            payment_date=timezone.localdate(),
            period_month=month,
            period_year=year,
        )
        process_payment(
            tenant=self.tenant,
            amount=Decimal("7000"),
            payment_date=timezone.localdate(),
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
            payment_date=timezone.localdate(),
            period_month=month,
            period_year=year,
        )
        arrears = Arrears.objects.get(tenant=self.tenant, period_month=month, period_year=year)
        assert arrears.is_cleared
        assert arrears.balance == Decimal("0")
        assert arrears.amount_paid == Decimal("15000")

    # --- Waiver preservation (M1) --------------------------------------

    def test_waiver_not_reversed_by_later_payment(self):
        """A partial-period waiver must survive a subsequent payment."""
        month, year = self._now()
        # Tenant pays 4000 of 10000 → 6000 outstanding.
        process_payment(
            tenant=self.tenant,
            amount=Decimal("4000"),
            payment_date=timezone.localdate(),
            period_month=month,
            period_year=year,
        )
        arrears = Arrears.objects.get(tenant=self.tenant, period_month=month, period_year=year)
        assert arrears.balance == Decimal("6000")

        # Admin waives the remaining 6000 (mirrors the waive endpoint).
        arrears.waived_amount = arrears.balance
        arrears.balance = Decimal("0")
        arrears.is_cleared = True
        arrears.waive_notes = "Goodwill waiver"
        arrears.save()

        # A later payment for the same period must NOT reverse the waiver.
        process_payment(
            tenant=self.tenant,
            amount=Decimal("1000"),
            payment_date=timezone.localdate(),
            period_month=month,
            period_year=year,
        )
        arrears.refresh_from_db()
        # paid = 5000, waived = 6000, expected = 10000 → fully covered.
        assert arrears.waived_amount == Decimal("6000")
        assert arrears.waive_notes == "Goodwill waiver"
        assert arrears.is_cleared
        assert arrears.balance == Decimal("0")

    def test_partial_waiver_balance_accounts_for_payment(self):
        """Balance after a payment should net out paid + waived against rent."""
        month, year = self._now()
        process_payment(
            tenant=self.tenant,
            amount=Decimal("2000"),
            payment_date=timezone.localdate(),
            period_month=month,
            period_year=year,
        )
        arrears = Arrears.objects.get(tenant=self.tenant, period_month=month, period_year=year)
        # Waive 3000 only (partial); 10000 - 2000 - 3000 = 5000 still owed.
        arrears.waived_amount = Decimal("3000")
        arrears.balance = Decimal("5000")
        arrears.is_cleared = False
        arrears.save()

        # Record another 1000 → paid 3000, waived 3000 → balance 4000.
        process_payment(
            tenant=self.tenant,
            amount=Decimal("1000"),
            payment_date=timezone.localdate(),
            period_month=month,
            period_year=year,
        )
        arrears.refresh_from_db()
        assert arrears.waived_amount == Decimal("3000")
        assert arrears.balance == Decimal("4000")
        assert not arrears.is_cleared

    def test_waive_endpoint_marks_current_unit_paid(self):
        """Waiving the current-period balance must leave the unit PAID, not PARTIAL.

        Previously the endpoint recalculated status from cash paid only, so a
        partially-paid period that was then fully waived left the unit stuck at
        OCCUPIED_PARTIAL. It must reflect paid + waived == rent → PAID.
        """
        month, year = self._now()
        process_payment(
            tenant=self.tenant,
            amount=Decimal("4000"),
            payment_date=timezone.localdate(),
            period_month=month,
            period_year=year,
        )
        arrears = Arrears.objects.get(tenant=self.tenant, period_month=month, period_year=year)
        self.unit.refresh_from_db()
        assert self.unit.status == UnitStatus.OCCUPIED_PARTIAL

        resp = self.client.post(f"/api/arrears/{arrears.id}/waive/")
        assert resp.status_code == status.HTTP_200_OK

        arrears.refresh_from_db()
        assert arrears.is_cleared
        assert arrears.balance == Decimal("0")
        assert arrears.waived_amount == Decimal("6000")

        self.unit.refresh_from_db()
        assert self.unit.status == UnitStatus.OCCUPIED_PAID

    # --- API-level tests -----------------------------------------------

    def test_create_payment_via_api(self):
        month, year = self._now()
        resp = self.client.post("/api/payments/", {
            "tenant": self.tenant.id,
            "amount": "10000.00",
            "payment_date": timezone.localdate().isoformat(),
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
            payment_date=timezone.localdate(),
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
            payment_date=timezone.localdate(),
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
            payment_date=timezone.localdate(),
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
            "payment_date": timezone.localdate().isoformat(),
            "period_month": month,
            "period_year": year,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_unauthenticated_denied(self):
        anon = APIClient()
        resp = anon.get("/api/payments/")
        assert resp.status_code == 401

    # --- Idempotency (double-processing guard) -------------------------

    def test_idempotency_key_prevents_double_booking(self):
        """A re-submitted payment with the same key returns the original and
        does not double-reduce arrears."""
        month, year = self._now()
        kwargs = dict(
            tenant=self.tenant,
            amount=Decimal("10000"),
            payment_date=timezone.localdate(),
            period_month=month,
            period_year=year,
            source="mpesa",
            reference="TXID-DUP-1",
            idempotency_key="TXID-DUP-1",
        )
        first = process_payment(**kwargs)
        second = process_payment(**kwargs)

        assert first.id == second.id  # same row returned, not a new booking
        assert Payment.objects.filter(tenant=self.tenant).count() == 1
        arrears = Arrears.objects.get(tenant=self.tenant, period_month=month, period_year=year)
        assert arrears.balance == Decimal("0")  # cleared exactly once

    def test_blank_key_allows_shared_reference(self):
        """FIFO splits one credit into several rows sharing a reference; a blank
        idempotency key must never dedupe them."""
        month, year = self._now()
        for _ in range(2):
            process_payment(
                tenant=self.tenant,
                amount=Decimal("2000"),
                payment_date=timezone.localdate(),
                period_month=month,
                period_year=year,
                source="bank",
                reference="SHARED-REF",  # same ref, no idempotency_key
            )
        assert Payment.objects.filter(tenant=self.tenant, reference="SHARED-REF").count() == 2

    def test_double_post_same_reference_is_idempotent(self):
        """Double-submitting the create API with the same reference books once."""
        month, year = self._now()
        body = {
            "tenant": self.tenant.id,
            "amount": "10000.00",
            "payment_date": timezone.localdate().isoformat(),
            "period_month": month,
            "period_year": year,
            "source": "mpesa",
            "reference": "TXID-API-1",
        }
        r1 = self.client.post("/api/payments/", body, format="json")
        r2 = self.client.post("/api/payments/", body, format="json")
        assert r1.status_code == status.HTTP_201_CREATED
        assert r2.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
        assert Payment.objects.filter(tenant=self.tenant, reference="TXID-API-1").count() == 1


class CommercialVatTransactionTests(APITestCase):
    """process_payment must split VAT OUT of a commercial gross receipt for the
    Transaction/receipt — matching the ledger — never gross it up on top."""

    @classmethod
    def setUpTestData(cls):
        cls.building = Building.objects.create(name="MC Arcade", code="MCG", total_floors=1)
        cls.unit = Unit.objects.create(
            building=cls.building,
            label="MCG01",
            monthly_rent=Decimal("24000"),  # base (ex-VAT) per import_matasia
            classification=UnitClassification.BUSINESS,
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        cls.tenant = Tenant.objects.create(
            first_name="Comm", last_name="Tenant", id_number="MC001",
            phone="+254700000900", unit=cls.unit,
            monthly_rent=Decimal("24000"), move_in_date="2026-01-01",
        )

    def test_commercial_transaction_splits_vat_out_of_gross(self):
        today = timezone.localdate()
        # Tenant pays the gross figure: 24,000 rent + 3,840 VAT = 27,840.
        payment = process_payment(
            tenant=self.tenant,
            amount=Decimal("27840.00"),
            payment_date=today,
            period_month=today.month,
            period_year=today.year,
            source="mpesa",
            reference="MC-TXN-1",
        )
        # Payment.amount stays the gross received (the ledger + arrears read it).
        assert payment.amount == Decimal("27840.00")

        txn = Transaction.objects.get(payment=payment)
        assert txn.base_amount == Decimal("24000.00")   # net income
        assert txn.tax_amount == Decimal("3840.00")     # 16% VAT
        assert txn.total_amount == Decimal("27840.00")  # gross == payment.amount
        # net + vat reconciles to the gross exactly.
        assert txn.base_amount + txn.tax_amount == payment.amount

    def test_residential_transaction_has_no_vat(self):
        res_unit = Unit.objects.create(
            building=self.building, label="DON1A",
            monthly_rent=Decimal("20000"),
            classification=UnitClassification.RESIDENTIAL,
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        res_tenant = Tenant.objects.create(
            first_name="Res", last_name="Tenant", id_number="RES001",
            phone="+254700000901", unit=res_unit,
            monthly_rent=Decimal("20000"), move_in_date="2026-01-01",
        )
        today = timezone.localdate()
        payment = process_payment(
            tenant=res_tenant, amount=Decimal("20000.00"),
            payment_date=today, period_month=today.month, period_year=today.year,
        )
        txn = Transaction.objects.get(payment=payment)
        assert txn.base_amount == Decimal("20000.00")
        assert txn.tax_amount == Decimal("0.00")
        assert txn.total_amount == Decimal("20000.00")

    def test_split_tax_inclusive_reconciles(self):
        r = split_tax_inclusive(Decimal("27840.00"), UnitClassification.BUSINESS)
        assert r.base_amount == Decimal("24000.00")
        assert r.tax_amount == Decimal("3840.00")
        assert r.total_amount == Decimal("27840.00")
        assert r.base_amount + r.tax_amount == r.total_amount
