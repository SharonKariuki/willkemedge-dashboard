"""An edited deposit has to reach the books and the statement, not just the card.

``Tenant.deposit_paid`` saved fine, but the statement and 2100 read DEPOSIT
payments, so a director who changed a deposit saw the old figure the moment a
statement was drawn and reasonably concluded the edit had not stuck. The same
went for an agreed deposit: stored, and absent from the PDF.
"""
import datetime as _dt
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.template.loader import render_to_string
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.ledger.models import JournalEntry, JournalLine
from apps.ledger.posting import post_opening_balances
from apps.payments.models import Payment, PaymentType
from apps.payments.services import process_payment
from apps.payments.statement_service import build_statement
from apps.tenants.deposits import deposit_held_on_books
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
D = Decimal


class DepositBookingTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="director", email="director@test.com",
            password="testpass123!", role="owner",
        )
        cls.building = Building.objects.create(name="Wilkem Edge", code="WED", total_floors=2)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _let(self, label, rent="15000", held="0", classification=UnitClassification.RESIDENTIAL):
        unit = Unit.objects.create(
            building=self.building, label=label, monthly_rent=D(rent),
            classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name=label, last_name="Tenant", id_number=f"ID-{label}",
            phone="+254711111111", unit=unit, monthly_rent=D(rent),
            deposit_paid=D(held), move_in_date="2026-07-01", status=TenantStatus.ACTIVE,
        )

    def _edit(self, tenant, expect=status.HTTP_200_OK, **fields):
        resp = self.client.patch(f"/api/tenants/{tenant.id}/", fields, format="json")
        assert resp.status_code == expect, resp.content
        tenant.refresh_from_db()
        return resp

    def _deposits(self, tenant):
        return list(
            Payment.objects.filter(
                tenant=tenant, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True,
            ).order_by("payment_date", "created_at")
        )


class EditingTheDepositBooksIt(DepositBookingTestCase):
    def test_raising_the_deposit_books_the_difference(self):
        tenant = self._let("WED20")

        self._edit(tenant, deposit_paid="14000")
        self._edit(tenant, deposit_paid="15000")

        assert [p.amount for p in self._deposits(tenant)] == [D("14000.00"), D("1000.00")]
        assert tenant.deposit_paid == D("15000.00")
        assert deposit_held_on_books(tenant) == D("15000.00")

    def test_the_booking_is_a_liability_not_income(self):
        tenant = self._let("WED21")

        self._edit(tenant, deposit_paid="15000")

        entry = JournalEntry.objects.get(source_type="payment", source_id=self._deposits(tenant)[0].pk)
        lines = {
            line.account.code: (line.debit, line.credit)
            for line in JournalLine.objects.filter(entry=entry).select_related("account")
        }
        assert lines["1030"] == (D("15000.00"), D("0.00"))
        assert lines["2100"] == (D("0.00"), D("15000.00"))

    def test_the_statement_shows_the_edited_deposit(self):
        tenant = self._let("WED22")

        self._edit(tenant, deposit_paid="15000")

        st = build_statement(tenant)
        assert st["security_deposit"] == "15,000.00"
        assert "One Month Rent Deposit" in [r["description"] for r in st["rows"]]
        assert "Security Deposit Held" in render_to_string("payments/statement_pdf.html", st)

    def test_lowering_rebooks_the_remainder_on_the_date_it_was_received(self):
        tenant = self._let("WED23", held="20000")
        process_payment(
            tenant=tenant, amount=D("20000"), payment_date=_dt.date(2026, 7, 1),
            period_month=7, period_year=2026, source="mpesa", reference="TJ4X9QW1ZP",
            payment_type=PaymentType.DEPOSIT, idempotency_key="move-in",
        )

        self._edit(tenant, deposit_paid="15000")

        [kept] = self._deposits(tenant)
        assert kept.amount == D("15000.00")
        assert kept.payment_date == _dt.date(2026, 7, 1)
        assert kept.reference == "TJ4X9QW1ZP"
        assert deposit_held_on_books(tenant) == D("15000.00")
        assert tenant.deposit_paid == D("15000.00")

    def test_returning_to_an_earlier_figure_books_it_again(self):
        """Same day, same figure twice — not a replay of the first booking."""
        tenant = self._let("WED24")

        self._edit(tenant, deposit_paid="14000")
        self._edit(tenant, deposit_paid="10000")
        self._edit(tenant, deposit_paid="14000")

        assert deposit_held_on_books(tenant) == D("14000.00")

    def test_a_cutover_deposit_cannot_be_reduced_from_the_form(self):
        tenant = self._let("WED25", held="15000")
        post_opening_balances(tenant, net_balance=0, deposit=D("15000"), date=_dt.date(2026, 7, 1))

        resp = self._edit(tenant, expect=status.HTTP_400_BAD_REQUEST, deposit_paid="10000")

        assert "deposit_paid" in resp.json()
        assert tenant.deposit_paid == D("15000.00"), "the rejected edit still saved"
        assert not Payment.objects.filter(tenant=tenant).exists()

    def test_an_unrelated_edit_books_nothing(self):
        """The form re-sends deposit_paid on every save; an unchanged figure on a
        tenant whose books lag the card must not book a deposit."""
        tenant = self._let("WED26", held="14000")

        self._edit(tenant, phone="+254700111222")
        self._edit(tenant, phone="+254700111333", deposit_paid="14000")

        assert not Payment.objects.filter(tenant=tenant).exists()

    def test_the_payment_history_reads_the_books(self):
        tenant = self._let("WED27", held="15000")
        post_opening_balances(tenant, net_balance=0, deposit=D("15000"), date=_dt.date(2026, 7, 1))

        resp = self.client.get(f"/api/tenants/{tenant.id}/payment-history/")

        assert resp.json()["security_deposit"] == "15000.00"


class TheStatementCarriesTheAgreedDeposit(DepositBookingTestCase):
    def test_an_agreed_deposit_is_labelled_and_printed(self):
        tenant = self._let("WED30", rent="15000")

        self._edit(tenant, agreed_deposit="14000", deposit_paid="14000")

        st = build_statement(tenant)
        assert "Rent Security Deposit (Agreed)" in [r["description"] for r in st["rows"]]
        assert st["deposit_is_agreed"] is True
        assert st["agreed_deposit"] == "14,000.00"
        html = render_to_string("payments/statement_pdf.html", st)
        assert "Agreed Security Deposit" in html
        assert "14,000.00" in html

    def test_a_deposit_on_the_rule_prints_no_agreed_line(self):
        tenant = self._let("WED31", rent="15000")

        self._edit(tenant, deposit_paid="15000")

        html = render_to_string("payments/statement_pdf.html", build_statement(tenant))
        assert "Agreed Security Deposit" not in html

    def test_a_cutover_deposit_reaches_the_statement(self):
        tenant = self._let("WED32", held="15000")
        post_opening_balances(tenant, net_balance=0, deposit=D("15000"), date=_dt.date(2026, 7, 1))

        assert build_statement(tenant)["security_deposit"] == "15,000.00"


class TheBooksFollowTheEdit(DepositBookingTestCase):
    """What the Accounting page shows, not only what the posting code writes."""

    def _held_on_balance_sheet(self):
        today = _dt.date.today()
        resp = self.client.get(
            f"/api/reports/accounting/?tab=balance_sheet&month={today.month}&year={today.year}"
        )
        assert resp.status_code == status.HTTP_200_OK, resp.content
        body = resp.json()
        assert body["balanced"] is True
        return (
            D(str(body["liabilities"]["2100 Tenant Security Deposits Held"])),
            D(str(body["assets"]["1030 Tenant Security Deposit Bank Account"])),
        )

    def test_the_balance_sheet_follows_a_raise_and_a_cut(self):
        tenant = self._let("WED50")

        self._edit(tenant, deposit_paid="15000")
        assert self._held_on_balance_sheet() == (D("15000"), D("15000"))

        self._edit(tenant, deposit_paid="12000")
        assert self._held_on_balance_sheet() == (D("12000"), D("12000"))

    def test_a_commercial_deposit_carries_no_vat(self):
        """The 16% is split out of commercial RENT; a deposit is not income."""
        tenant = self._let("MCG50", rent="50000", classification=UnitClassification.BUSINESS)

        self._edit(tenant, deposit_paid="150000")

        codes = set(
            JournalLine.objects.filter(
                entry__source_type="payment",
                entry__source_id=self._deposits(tenant)[0].pk,
            ).values_list("account__code", flat=True)
        )
        assert codes == {"1030", "2100"}
        assert self._held_on_balance_sheet() == (D("150000"), D("150000"))

    def test_an_edit_that_cannot_reach_the_ledger_is_not_saved(self):
        from unittest.mock import patch

        tenant = self._let("WED51")

        with patch("apps.ledger.posting.post_payment", side_effect=RuntimeError("GL down")):
            resp = self._edit(tenant, expect=status.HTTP_400_BAD_REQUEST, deposit_paid="15000")

        assert "ledger" in resp.json()["deposit_paid"][0]
        assert tenant.deposit_paid == D("0.00")
        assert not Payment.objects.filter(tenant=tenant).exists()


class SyncDepositBookingsTests(DepositBookingTestCase):
    def _run(self, *args):
        out = StringIO()
        call_command("sync_deposit_bookings", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_books_nothing(self):
        tenant = self._let("WED40", held="15000")

        out = self._run()

        assert "DRY-RUN" in out
        assert not Payment.objects.filter(tenant=tenant).exists()

    def test_apply_books_only_what_the_card_has_beyond_the_books(self):
        tenant = self._let("WED41", held="15000")
        post_opening_balances(tenant, net_balance=0, deposit=D("10000"), date=_dt.date(2026, 7, 1))

        self._run("--apply", "--on", "2026-09-01")

        [booked] = self._deposits(tenant)
        assert booked.amount == D("5000.00")
        assert booked.payment_date == _dt.date(2026, 9, 1)
        assert deposit_held_on_books(tenant) == D("15000.00")
        assert "Nothing to book" in self._run("--apply")

    def test_books_above_the_card_are_reported_not_changed(self):
        tenant = self._let("WED42", held="5000")
        post_opening_balances(tenant, net_balance=0, deposit=D("15000"), date=_dt.date(2026, 7, 1))

        out = self._run("--apply")

        assert "REPORTED ONLY" in out
        assert not Payment.objects.filter(tenant=tenant).exists()
