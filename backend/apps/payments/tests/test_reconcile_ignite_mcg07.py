"""
MCG07 reconciled to the issued September 2026 statement.

Three faults stack on this account — the deposit booked as rent, August billed
when the tenancy starts in September, and October raised before the 25 Sept
run. Fixing any one alone moves the balance further from the truth, so the
command asserts the whole end state:

    Arrears / Others     0.00
    Current Month       60,000.00 + 9,600.00 VAT
    Total KES Due       69,600.00
    Security Deposit   180,000.00
"""
import datetime as _dt
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.ledger.models import JournalEntry
from apps.payments.models import Arrears, Payment, PaymentSource, PaymentType
from apps.payments.services import process_payment
from apps.payments.statement_service import build_statement
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
PAY_DATE = _dt.date(2026, 8, 24)
DEPOSIT = D("180000.00")


def _lines(source_type, source_id, kind):
    entry = JournalEntry.objects.filter(
        source_type=source_type, source_id=source_id, kind=kind
    ).first()
    return {} if entry is None else {ln.account.code: (ln.debit, ln.credit) for ln in entry.lines.all()}


@pytest.fixture
def mcg07(db):
    """Production's shape: Aug/Sep/Oct billed, 180,000 sitting in as rent."""
    building = Building.objects.create(
        name="Wilkem Edge Business Arcade", code="MC", total_floors=2
    )
    unit = Unit.objects.create(
        building=building, label="MCG07", monthly_rent=D("60000"),
        classification=UnitClassification.BUSINESS, status=UnitStatus.OCCUPIED_UNPAID,
    )
    tenant = Tenant.objects.create(
        first_name="Ignite Access (KE)", last_name="Limited", id_number="IG-MCG07",
        phone="+254727070946", unit=unit, monthly_rent=D("60000"),
        move_in_date="2026-09-01", status=TenantStatus.ACTIVE,
    )
    for month in (8, 9, 10):
        Arrears.objects.create(
            tenant=tenant, period_month=month, period_year=2026,
            expected_rent=D("60000"), expected_vat=D("9600"),
            amount_paid=D("0"), balance=D("69600"), is_cleared=False,
        )
    payment = process_payment(
        tenant=tenant, amount=DEPOSIT, payment_date=PAY_DATE,
        period_month=8, period_year=2026, source=PaymentSource.BANK,
        reference="FT26236ABCD",
    )
    return tenant, payment


def test_before_the_repair_the_account_reads_28800(mcg07):
    """The figure on the live statement — three months billed, less 180,000."""
    tenant, _ = mcg07
    statement = build_statement(tenant, statement_date=_dt.date(2026, 10, 1))
    assert statement["total_due"] == "28,800.00"


def test_preview_writes_nothing(mcg07):
    tenant, payment = mcg07
    out = StringIO()

    call_command("reconcile_ignite_mcg07", stdout=out)

    assert "DRY RUN" in out.getvalue()
    payment.refresh_from_db()
    assert payment.voided_at is None
    assert Arrears.objects.filter(tenant=tenant).count() == 3


def test_repair_produces_the_issued_statement(mcg07):
    tenant, payment = mcg07

    call_command("reconcile_ignite_mcg07", "--apply", stdout=StringIO())

    statement = build_statement(tenant, statement_date=_dt.date(2026, 9, 1))
    assert statement["arrears_others"] == "0.00"
    assert statement["current_month_rent"] == "60,000.00"
    assert statement["vat_on_rent"] == "9,600.00"
    assert statement["total_due"] == "69,600.00"
    assert statement["security_deposit"] == "180,000.00"


def test_august_and_october_are_removed_september_kept(mcg07):
    tenant, _ = mcg07

    call_command("reconcile_ignite_mcg07", "--apply", stdout=StringIO())

    months = sorted(
        Arrears.objects.filter(tenant=tenant).values_list("period_month", flat=True)
    )
    assert months == [9]


def test_deposit_moves_off_rental_income_and_vat(mcg07):
    tenant, payment = mcg07
    payment_pk = payment.pk

    call_command("reconcile_ignite_mcg07", "--apply", stdout=StringIO())

    # The wrong entry is reversed — 155,172.41 income and 24,827.59 VAT undone.
    reversal = _lines("payment", payment_pk, "reversal")
    assert reversal["4120"][0] == D("155172.41")
    assert reversal["2600"][0] == D("24827.59")

    deposit = Payment.objects.get(tenant=tenant, payment_type=PaymentType.DEPOSIT)
    lines = _lines("payment", deposit.pk, "normal")
    assert lines["1030"] == (DEPOSIT, D("0.00"))
    assert lines["2100"] == (D("0.00"), DEPOSIT)
    assert "4120" not in lines
    assert "2600" not in lines

    tenant.refresh_from_db()
    assert tenant.deposit_paid == DEPOSIT


def test_a_period_carrying_cash_is_never_removed(mcg07):
    """October with a real payment against it is a human's call, not the command's."""
    tenant, _ = mcg07
    process_payment(
        tenant=tenant, amount=D("69600"), payment_date=_dt.date(2026, 10, 2),
        period_month=10, period_year=2026, source=PaymentSource.MPESA, reference="OCT",
    )
    out = StringIO()

    call_command("reconcile_ignite_mcg07", "--apply", stdout=out)

    assert "SKIPPED" in out.getvalue()
    assert Arrears.objects.filter(tenant=tenant, period_month=10).exists()
    # Keeping it is right, and costs nothing: October's charge and the cash
    # against it cancel, so the account still foots to the issued statement.
    assert build_statement(
        tenant, statement_date=_dt.date(2026, 9, 1)
    )["total_due"] == "69,600.00"


def test_rerun_is_idempotent(mcg07):
    tenant, _ = mcg07

    call_command("reconcile_ignite_mcg07", "--apply", stdout=StringIO())
    call_command("reconcile_ignite_mcg07", "--apply", stdout=StringIO())

    assert build_statement(
        tenant, statement_date=_dt.date(2026, 9, 1)
    )["total_due"] == "69,600.00"
    assert Payment.objects.filter(
        tenant=tenant, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True
    ).count() == 1
