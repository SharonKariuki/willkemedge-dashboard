"""Registering a letting must put the deposit on the books, not just on the card.

``Tenant.deposit_paid`` is a note of how much is held; it moves no money. Before
this, registering a tenant wrote that number and stopped — so 1030 (Tenant
Security Deposit Bank) and 2100 (Tenant Security Deposits Held) never moved, and
a deposit showed on the tenant's card while being absent from the balance sheet.
Tenants who predate the cutover only have theirs booked because
``post_opening_balances`` posted it; anyone registered afterwards had nothing.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.ledger.models import JournalEntry, JournalLine
from apps.payments.models import Arrears, Payment, PaymentSource, PaymentType
from apps.tenants.models import Tenant

from apps.buildings.models import (  # isort: skip
    Building,
    Unit,
    UnitClassification,
    UnitStatus,
)

User = get_user_model()
D = Decimal


class MoveInDepositBookingTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="registrar", email="registrar@test.com",
            password="testpass123!", role="owner",
        )
        cls.building = Building.objects.create(name="Wilkem Edge", code="WED")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _vacant(self, label, rent, classification=UnitClassification.RESIDENTIAL):
        return Unit.objects.create(
            building=self.building, label=label, monthly_rent=D(rent),
            classification=classification, status=UnitStatus.VACANT,
        )

    def _register(self, unit, **overrides):
        payload = {
            "first_name": "Grace", "last_name": "Wanjiru",
            "id_number": f"ID-{unit.label}", "phone": "+254711111111",
            "unit": unit.id, "monthly_rent": str(unit.monthly_rent),
            "deposit_paid": str(unit.monthly_rent),
            "move_in_date": "2026-09-01",
        }
        payload.update(overrides)
        return self.client.post("/api/tenants/", payload, format="json")

    def _lines(self, payment):
        entry = JournalEntry.objects.get(source_type="payment", source_id=payment.pk)
        return {
            line.account.code: (line.debit, line.credit)
            for line in JournalLine.objects.filter(entry=entry).select_related("account")
        }

    # --- the deposit reaches the ledger ------------------------------------

    def test_registering_with_a_deposit_books_it(self):
        unit = self._vacant("WED1A", "20000")

        response = self._register(unit)
        assert response.status_code == status.HTTP_201_CREATED, response.data

        tenant = Tenant.objects.get(pk=response.data["id"])
        payment = Payment.objects.get(tenant=tenant)

        assert payment.payment_type == PaymentType.DEPOSIT
        assert payment.amount == D("20000")
        assert payment.created_by == self.user

    def test_the_journal_entry_debits_1030_and_credits_2100(self):
        """A deposit is a liability held, never income."""
        unit = self._vacant("WED1B", "20000")
        self._register(unit)

        lines = self._lines(Payment.objects.get())

        assert lines["1030"] == (D("20000.00"), D("0.00"))
        assert lines["2100"] == (D("0.00"), D("20000.00"))
        assert "4110" not in lines and "4120" not in lines

    def test_the_deposit_settles_no_rent(self):
        """It must not be mistaken for the first month's rent."""
        unit = self._vacant("WED1C", "20000")
        self._register(unit)

        assert not Arrears.objects.filter(amount_paid__gt=0).exists()

    # --- what the form captures --------------------------------------------

    def test_the_payment_carries_how_when_and_under_what_reference(self):
        unit = self._vacant("WED1D", "20000")

        self._register(
            unit,
            deposit_source=PaymentSource.MPESA,
            deposit_date="2026-09-03",
            deposit_reference="TJ4X9QW1ZP",
        )
        payment = Payment.objects.get()

        assert payment.source == PaymentSource.MPESA
        assert str(payment.payment_date) == "2026-09-03"
        assert payment.reference == "TJ4X9QW1ZP"

    def test_the_deposit_defaults_to_the_move_in_date_and_to_cash(self):
        unit = self._vacant("WED1E", "20000")
        self._register(unit)
        payment = Payment.objects.get()

        assert str(payment.payment_date) == "2026-09-01"
        assert payment.source == PaymentSource.CASH

    def test_a_deposit_cannot_predate_the_move_in(self):
        unit = self._vacant("WED1F", "20000")

        response = self._register(unit, deposit_date="2026-08-20")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "deposit_date" in response.data
        assert not Tenant.objects.exists()

    # --- the cases that must book nothing ----------------------------------

    def test_no_deposit_books_no_payment(self):
        unit = self._vacant("WED1G", "20000")

        response = self._register(unit, deposit_paid="0")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Tenant.objects.count() == 1
        assert not Payment.objects.exists()
        assert not JournalEntry.objects.filter(source_type="payment").exists()

    def test_a_caretaker_registered_rent_free_is_not_billed(self):
        """The create endpoint honours the exemption, not only the seeder."""
        unit = self._vacant("WEDCH", "0")

        response = self._register(
            unit, monthly_rent="0", deposit_paid="0", is_billable=False,
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Tenant.objects.get().is_billable is False

    # --- the registration and the booking stand or fall together -----------

    def test_a_failed_posting_rolls_the_whole_registration_back(self):
        """The state this exists to prevent is a tenant whose deposit is only a
        number, so a deposit that cannot be booked must not leave one behind."""
        from unittest.mock import patch

        unit = self._vacant("WED1H", "20000")

        with patch(
            "apps.tenants.views.record_initial_deposit",
            side_effect=RuntimeError("ledger unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self._register(unit)

        assert not Tenant.objects.exists()
        assert not Payment.objects.exists()
        unit.refresh_from_db()
        assert unit.status == UnitStatus.VACANT
