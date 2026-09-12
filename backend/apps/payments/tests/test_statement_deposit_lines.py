"""
The statement has to show the tenant the money they actually sent.

Deposits were left out of the ledger on the sound reasoning that a refundable
liability must not reduce the rent owed. Dropped from both columns, though, a
tenant who transferred 75,000 got a statement acknowledging 25,000 — Fortcom
(MCF01) exactly. And a single transfer stored as several Payment rows, which is
what FIFO allocation and a deposit/first-month split both produce, printed as
several payments they never made.

The acceptance test is the last one: MCF01's statement as at 1 Sept 2026 must
reproduce the landlord's own document, row for row.
"""
import datetime as _dt
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.statement_service import build_statement
from apps.tenants.models import Tenant, TenantStatus

D = Decimal

REF = "S48023247_10082026_2"


@pytest.fixture
def arcade(db):
    return Building.objects.create(
        name="Wilkem Edge Business Arcade", code="MC", total_floors=2
    )


@pytest.fixture
def let(arcade, db):
    def _let(label, rent="25000", **kw):
        unit = Unit.objects.create(
            building=arcade, label=label, monthly_rent=D(rent),
            classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name=label, last_name="Ltd", id_number=f"D-{label}",
            phone="0794969696", unit=unit, monthly_rent=D(rent),
            deposit_paid=D(0), move_in_date="2026-08-10",
            status=TenantStatus.ACTIVE, **kw,
        )
    return _let


def _charge(tenant, month, rent="25000", vat="4000"):
    from apps.payments.models import Arrears

    return Arrears.objects.create(
        tenant=tenant, period_year=2026, period_month=month,
        expected_rent=D(rent), expected_vat=D(vat),
        amount_paid=D(0), balance=D(rent) + D(vat), is_cleared=False,
    )


def _pay(tenant, amount, *, kind="rent", day=10, month=8, ref=REF, key=None):
    from apps.payments.services import process_payment

    return process_payment(
        tenant=tenant, amount=D(amount), payment_date=_dt.date(2026, month, day),
        period_month=8, period_year=2026, source="bank", reference=ref,
        idempotency_key=key or f"{ref}#{kind}-{amount}-{month}{day}",
        payment_type=kind,
    )


def _ledger(tenant, on="2026-09-01"):
    when = _dt.date.fromisoformat(on)
    st = build_statement(tenant, statement_date=when, as_of=when)
    return st, [
        (r["posting_date"], r["description"], r["invoice_amount"], r["payment"], r["balance"])
        for r in st["rows"]
    ]


class TestTheDepositIsVisible:
    def test_the_money_received_is_shown_in_full(self, let):
        tenant = let("MCD01")
        _charge(tenant, 8)
        _pay(tenant, "50000", kind="deposit")
        _pay(tenant, "25000")

        _st, rows = _ledger(tenant)

        assert ("10 Aug 2026", "Payment Received", "", "75,000", "(75,000)") in rows

    def test_the_deposit_is_invoiced_straight_back_out(self, let):
        tenant = let("MCD01")
        _charge(tenant, 8)
        _pay(tenant, "50000", kind="deposit")
        _pay(tenant, "25000")

        _st, rows = _ledger(tenant)

        assert ("10 Aug 2026", "Two Months Rent Deposit", "50,000", "", "(25,000)") in rows

    def test_the_pair_nets_to_nothing_against_rent(self, let):
        """The whole safety property: showing the deposit must not pay rent down.
        29,000 charged, 25,000 of rent received, so 4,000 is owed either way."""
        with_deposit = let("MCD01")
        _charge(with_deposit, 8)
        _pay(with_deposit, "50000", kind="deposit")
        _pay(with_deposit, "25000")

        without = let("MCD02")
        _charge(without, 8)
        _pay(without, "25000", ref="OTHER")

        assert _ledger(with_deposit)[0]["total_due"] == _ledger(without)[0]["total_due"]
        assert _ledger(with_deposit)[0]["total_due"] == "4,000.00"

    def test_the_deposit_is_not_counted_twice_in_the_breakdown(self, let):
        tenant = let("MCD01")
        _charge(tenant, 8)
        _pay(tenant, "50000", kind="deposit")

        st, _rows = _ledger(tenant)

        assert st["security_deposit"] == "50,000.00"

    def test_a_voided_payment_stays_off_the_statement(self, let):
        from apps.payments.services import void_payment

        tenant = let("MCD01")
        _charge(tenant, 8)
        void_payment(_pay(tenant, "50000", kind="deposit"), reason="mis-keyed")

        _st, rows = _ledger(tenant)

        assert not [r for r in rows if "Deposit" in r[1]]
        assert not [r for r in rows if r[1] == "Payment Received"]


class TestTheDepositLabel:
    @pytest.mark.parametrize(
        "amount,expected",
        [
            ("25000", "One Month Rent Deposit"),
            ("50000", "Two Months Rent Deposit"),
            ("75000", "Three Months Rent Deposit"),
        ],
    )
    def test_names_whole_months_the_way_the_lease_does(self, let, amount, expected):
        tenant = let("MCD01")
        _charge(tenant, 8)
        _pay(tenant, amount, kind="deposit")

        _st, rows = _ledger(tenant)

        assert [r[1] for r in rows if "Deposit" in r[1]] == [expected]

    def test_an_odd_figure_is_not_described_in_months(self, let):
        """A month count that is not true is worse than no month count."""
        tenant = let("MCD01")
        _charge(tenant, 8)
        _pay(tenant, "37500", kind="deposit")

        _st, rows = _ledger(tenant)

        assert [r[1] for r in rows if "Deposit" in r[1]] == ["Rent Security Deposit"]


class TestCreditBalancesAreBracketed:
    def test_a_credit_balance_prints_in_brackets(self, let):
        """The landlord's sheet shows (75,000), not -75,000.

        The receipt lands before the charges it settles, so the running balance
        opens in credit and stays there for two rows. A minus sign reads as a
        typo beside five unsigned figures.
        """
        tenant = let("MCD01")
        _charge(tenant, 8)
        _pay(tenant, "50000", kind="deposit")
        _pay(tenant, "25000")

        _st, rows = _ledger(tenant)

        balances = [r[4] for r in rows]
        assert balances == ["(75,000)", "(25,000)", "0", "4,000"]


class TestOneTransferIsOneLine:
    def test_a_credit_split_across_periods_prints_once(self, let):
        """FIFO cuts one bank credit into a row per period it settles. The
        tenant made one payment and should see one line."""
        tenant = let("MCD01")
        _charge(tenant, 8)
        _charge(tenant, 9)
        _pay(tenant, "4000", ref="CB0289926", key="c1")
        _pay(tenant, "28000", ref="CB0289926", key="c2")

        _st, rows = _ledger(tenant)

        received = [r for r in rows if r[1] == "Payment Received"]
        assert [r[3] for r in received] == ["32,000"]

    def test_separate_transfers_stay_separate(self, let):
        tenant = let("MCD01")
        _charge(tenant, 8)
        _pay(tenant, "10000", ref="REF-A", key="a")
        _pay(tenant, "15000", ref="REF-B", key="b")

        _st, rows = _ledger(tenant)

        assert len([r for r in rows if r[1] == "Payment Received"]) == 2

    def test_unreferenced_cash_is_not_collapsed_together(self, let):
        """Two receipts with no reference are not evidence of one transfer."""
        tenant = let("MCD01")
        _charge(tenant, 8)
        _pay(tenant, "10000", ref="", key="x")
        _pay(tenant, "15000", ref="", key="y")

        _st, rows = _ledger(tenant)

        assert len([r for r in rows if r[1] == "Payment Received"]) == 2


class TestTheFortcomStatement:
    def test_reproduces_the_landlords_document(self, let):
        """MCF01 as at 1 Sept 2026, against the statement the landlord issued.

        The acceptance test for the whole document: same six rows, in the same
        order, on the same dates, carrying the same running balance down to the
        zero at row 3, and the same summary box. Nothing in it is incidental —
        each line failed at least once on the way here.
        """
        tenant = let("MCF01", care_of="Joseph M Kungu", kra_pin="P052143702J")
        _charge(tenant, 8)
        _charge(tenant, 9)
        _pay(tenant, "50000", kind="deposit")
        _pay(tenant, "25000")

        st, rows = _ledger(tenant)

        assert rows == [
            ("10 Aug 2026", "Payment Received", "", "75,000", "(75,000)"),
            ("10 Aug 2026", "Two Months Rent Deposit", "50,000", "", "(25,000)"),
            ("10 Aug 2026", "Month Rent - August-2026", "25,000", "", "0"),
            ("10 Aug 2026", "16% VAT on Rent", "4,000", "", "4,000"),
            ("31 Aug 2026", "Month Rent - Sept-2026", "25,000", "", "29,000"),
            ("31 Aug 2026", "16% VAT on Rent", "4,000", "", "33,000"),
        ]
        assert st["statement_date"] == "1 Sept 2026"
        assert st["total_due_whole"] == "33,000"
        # The summary box as the sheet states it: VAT inside the month's rent.
        assert st["arrears_others"] == "4,000.00"
        assert st["current_month_charged"] == "29,000.00"
        assert st["total_due"] == "33,000.00"
        # Still available apart, for the COA breakdown and the SMS.
        assert st["current_month_rent"] == "25,000.00"
        assert st["vat_on_rent"] == "4,000.00"
        assert st["security_deposit"] == "50,000.00"
        assert st["kra_pin"] == "P052143702J"
        assert st["care_of"] == "Joseph M Kungu"
        assert st["paybill_account"] == "90290#MCF01"

    def test_september_is_the_month_the_sheet_abbreviates(self, let):
        """'Sept-2026', not 'September-2026' and not '%b's 'Sep'.

        Every other month is written out, which is what the landlord's sheet
        does and is why this cannot just be strftime.
        """
        tenant = let("MCF01")
        _charge(tenant, 8)
        _charge(tenant, 9)

        _st, rows = _ledger(tenant)

        described = [r[1] for r in rows]
        assert "Month Rent - August-2026" in described
        assert "Month Rent - Sept-2026" in described


class TestWhenAChargeIsShownAsRaised:
    def test_commercial_rent_is_raised_at_the_close_of_the_month_before(self, let):
        """Billed for the month ahead: September's rent is dated 31 August."""
        tenant = let("MCF02")
        _charge(tenant, 9)

        _st, rows = _ledger(tenant)

        assert [r[0] for r in rows] == ["31 Aug 2026", "31 Aug 2026"]

    def test_a_first_month_is_never_dated_before_the_tenant_moved_in(self, let):
        """MCF01 holds the unit from 10 August, so August's rent is dated then,
        not 31 July — the tenant was not a tenant on 31 July."""
        tenant = let("MCF03")
        _charge(tenant, 8)

        _st, rows = _ledger(tenant)

        assert [r[0] for r in rows] == ["10 Aug 2026", "10 Aug 2026"]

    def test_septembers_rent_shown_in_august_is_not_august_arrears(self, let):
        """The safety property behind the split between the two dates.

        September's charge prints on 31 August but belongs to September, so it
        must not fall into the brought-forward figure the way a real August
        charge would. Fortcom carries 4,000 into September — the August VAT they
        came up short on — and nothing more.
        """
        tenant = let("MCF04")
        _charge(tenant, 8)
        _charge(tenant, 9)
        _pay(tenant, "50000", kind="deposit")
        _pay(tenant, "25000")

        st, _rows = _ledger(tenant)

        assert st["arrears_others"] == "4,000.00"
