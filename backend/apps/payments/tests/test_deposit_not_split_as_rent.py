"""
A security deposit is booked whole, to the deposit accounts — never as rent.

Ignite Access (KE) Limited paid 180,000 for the MCG07 security deposit on
24 Aug 2026. It landed as commercial rent — `allocate_payment_fifo` had no way
to express a payment type — and was cancelled off the statement by hand with an
equal "Rent Security Deposit" UtilityCharge. The tenant's closing balance came
out right; the books recognised 335,172.41 of income that does not exist and
declared 24,827.59 of VAT on a refundable liability.

Covers:
  * FIFO allocation books a non-rent credit whole and skips arrears (F1-F3)
  * the GL lands on 1030/2100, not 1020/4120/2600 (F4)
  * deleting a UtilityCharge reverses its journal entry (F5)
  * `repair_deposit_miscoding` re-books an existing miscoded pair (F6-F8)
"""
import datetime as _dt
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.ledger.models import JournalEntry
from apps.payments.models import (
    Arrears,
    Payment,
    PaymentSource,
    PaymentType,
    UtilityCharge,
)
from apps.payments.services import allocate_payment_fifo, process_payment
from apps.tenants.models import Tenant, TenantStatus

D = Decimal
PAY_DATE = _dt.date(2026, 8, 24)
DEPOSIT = D("180000.00")


def _lines(source_type, source_id, kind):
    """{account_code: (debit, credit)} for one journal entry."""
    entry = JournalEntry.objects.filter(
        source_type=source_type, source_id=source_id, kind=kind
    ).first()
    if entry is None:
        return {}
    return {ln.account.code: (ln.debit, ln.credit) for ln in entry.lines.all()}


@pytest.fixture
def ignite(db):
    """MCG07 — commercial, 60,000/month, carrying two unpaid rent periods."""
    building = Building.objects.create(
        name="Wilkem Edge Business Arcade", code="MC", total_floors=2
    )
    unit = Unit.objects.create(
        building=building, label="MCG07", monthly_rent=D("60000"),
        classification=UnitClassification.BUSINESS,
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    tenant = Tenant.objects.create(
        first_name="Ignite Access (KE)", last_name="Limited",
        id_number="IGNITE-MCG07", phone="+254727070946",
        email="mineh.maina@igniteaccess.com", unit=unit,
        monthly_rent=D("60000"), move_in_date="2026-07-01",
        status=TenantStatus.ACTIVE,
    )
    for month in (7, 8):
        Arrears.objects.create(
            tenant=tenant, period_month=month, period_year=2026,
            expected_rent=D("60000"), expected_vat=D("9600"),
            amount_paid=D("0"), balance=D("69600"), is_cleared=False,
        )
    return tenant


# --- F1-F3: FIFO must not touch a non-rent credit ---------------------------

def test_deposit_is_booked_whole_and_not_split_across_arrears(ignite):
    """One Payment for the full 180,000 — not one chunk per open period."""
    created = allocate_payment_fifo(
        tenant=ignite, amount=DEPOSIT, payment_date=PAY_DATE,
        source=PaymentSource.BANK, reference="FT26236ABCD",
        payment_type=PaymentType.DEPOSIT,
    )

    assert len(created) == 1
    assert created[0].amount == DEPOSIT
    assert created[0].payment_type == PaymentType.DEPOSIT
    # Booked to the month the money arrived, not to the oldest open period.
    assert (created[0].period_month, created[0].period_year) == (8, 2026)


def test_deposit_does_not_discharge_rent_arrears(ignite):
    """Both rent periods still owe 69,600 after a 180,000 deposit."""
    allocate_payment_fifo(
        tenant=ignite, amount=DEPOSIT, payment_date=PAY_DATE,
        source=PaymentSource.BANK, reference="FT26236ABCD",
        payment_type=PaymentType.DEPOSIT,
    )

    for month in (7, 8):
        row = Arrears.objects.get(tenant=ignite, period_month=month, period_year=2026)
        assert row.amount_paid == D("0.00"), f"deposit settled {month}/2026"
        assert row.balance == D("69600.00")


def test_rent_still_splits_fifo(ignite):
    """The guard is scoped to non-rent — rent allocation is unchanged."""
    created = allocate_payment_fifo(
        tenant=ignite, amount=D("100000"), payment_date=PAY_DATE,
        source=PaymentSource.BANK, reference="FT26236RENT",
    )

    assert len(created) == 2
    assert [p.period_month for p in created] == [7, 8]
    assert created[0].amount == D("69600.00")   # July cleared first
    assert created[1].amount == D("30400.00")   # remainder onto August


def test_deposit_replay_is_idempotent(ignite):
    """The same bank transaction id twice must not book the deposit twice."""
    first = allocate_payment_fifo(
        tenant=ignite, amount=DEPOSIT, payment_date=PAY_DATE,
        source=PaymentSource.BANK, reference="FT26236ABCD",
        idempotency_key="FT26236ABCD", payment_type=PaymentType.DEPOSIT,
    )
    second = allocate_payment_fifo(
        tenant=ignite, amount=DEPOSIT, payment_date=PAY_DATE,
        source=PaymentSource.BANK, reference="FT26236ABCD",
        idempotency_key="FT26236ABCD", payment_type=PaymentType.DEPOSIT,
    )

    assert [p.pk for p in first] == [p.pk for p in second]
    assert Payment.objects.filter(tenant=ignite).count() == 1


# --- F4: the GL lands on the deposit accounts -------------------------------

def test_deposit_posts_to_1030_2100_and_raises_no_vat(ignite):
    """No 4120 income and no 2600 VAT on a refundable deposit."""
    payment = allocate_payment_fifo(
        tenant=ignite, amount=DEPOSIT, payment_date=PAY_DATE,
        source=PaymentSource.BANK, reference="FT26236ABCD",
        payment_type=PaymentType.DEPOSIT,
    )[0]

    lines = _lines("payment", payment.pk, "normal")
    assert lines["1030"] == (DEPOSIT, D("0.00"))
    assert lines["2100"] == (D("0.00"), DEPOSIT)
    assert "4120" not in lines, "deposit recognised as commercial rental income"
    assert "2600" not in lines, "VAT declared on a refundable deposit"


# --- F5: a deleted utility charge must leave the GL square ------------------

def test_deleting_a_utility_charge_posts_a_reversal(ignite):
    charge = UtilityCharge.objects.create(
        tenant=ignite, posting_date=PAY_DATE, period_month=8, period_year=2026,
        label="Water Usage", amount=D("3700"),
    )
    charge_pk = charge.pk
    assert _lines("utility_charge", charge_pk, "normal")["1040"] == (D("3700.00"), D("0.00"))

    charge.delete()

    reversal = _lines("utility_charge", charge_pk, "reversal")
    assert reversal["4150"] == (D("3700.00"), D("0.00"))
    assert reversal["1040"] == (D("0.00"), D("3700.00"))
    # The original stays put for audit.
    assert _lines("utility_charge", charge_pk, "normal")


# --- F6-F8: the repair command ---------------------------------------------

@pytest.fixture
def miscoded(ignite):
    """Reproduce the MCG07 shape: rent payment + offsetting deposit charge."""
    payment = process_payment(
        tenant=ignite, amount=DEPOSIT, payment_date=PAY_DATE,
        period_month=8, period_year=2026, source=PaymentSource.BANK,
        reference="FT26236ABCD",
    )
    charge = UtilityCharge.objects.create(
        tenant=ignite, posting_date=PAY_DATE, period_month=8, period_year=2026,
        label="Rent Security Deposit", amount=DEPOSIT,
    )
    return ignite, payment, charge


def test_repair_preview_writes_nothing(miscoded):
    tenant, payment, charge = miscoded
    out = StringIO()

    call_command("repair_deposit_miscoding", "--unit", "MCG07", stdout=out)

    assert "MCG07" in out.getvalue()
    assert "DRY RUN" in out.getvalue()
    payment.refresh_from_db()
    assert payment.voided_at is None
    assert UtilityCharge.objects.filter(pk=charge.pk).exists()


def test_repair_rebooks_the_deposit(miscoded):
    tenant, payment, charge = miscoded
    charge_pk = charge.pk

    call_command("repair_deposit_miscoding", "--unit", "MCG07", "--apply", stdout=StringIO())

    payment.refresh_from_db()
    assert payment.voided_at is not None
    assert not UtilityCharge.objects.filter(pk=charge_pk).exists()

    deposit = Payment.objects.get(tenant=tenant, payment_type=PaymentType.DEPOSIT)
    assert deposit.amount == DEPOSIT
    assert deposit.payment_date == PAY_DATE
    assert deposit.voided_at is None

    tenant.refresh_from_db()
    assert tenant.deposit_paid == DEPOSIT


def test_repair_leaves_the_gl_holding_only_the_deposit(miscoded):
    tenant, payment, charge = miscoded
    payment_pk, charge_pk = payment.pk, charge.pk

    call_command("repair_deposit_miscoding", "--unit", "MCG07", "--apply", stdout=StringIO())

    # Both wrong entries reversed...
    assert _lines("payment", payment_pk, "reversal")["4120"][0] == D("155172.41")
    assert _lines("payment", payment_pk, "reversal")["2600"][0] == D("24827.59")
    assert _lines("utility_charge", charge_pk, "reversal")["4150"][0] == DEPOSIT

    # ...and the deposit is the only thing left standing.
    deposit = Payment.objects.get(tenant=tenant, payment_type=PaymentType.DEPOSIT)
    lines = _lines("payment", deposit.pk, "normal")
    assert lines["1030"] == (DEPOSIT, D("0.00"))
    assert lines["2100"] == (D("0.00"), DEPOSIT)


def test_repair_leaves_arrears_untouched(miscoded):
    """The tenant still owes exactly what they owed — only the narration moves."""
    tenant, _payment, _charge = miscoded

    call_command("repair_deposit_miscoding", "--unit", "MCG07", "--apply", stdout=StringIO())

    for month in (7, 8):
        row = Arrears.objects.get(tenant=tenant, period_month=month, period_year=2026)
        assert row.balance == D("69600.00")


def test_repair_skips_an_ambiguous_pair(ignite):
    """Two candidate payments is a human's call, not the command's."""
    for ref in ("FT-A", "FT-B"):
        process_payment(
            tenant=ignite, amount=DEPOSIT, payment_date=PAY_DATE,
            period_month=8, period_year=2026, source=PaymentSource.BANK,
            reference=ref,
        )
    charge = UtilityCharge.objects.create(
        tenant=ignite, posting_date=PAY_DATE, period_month=8, period_year=2026,
        label="Rent Security Deposit", amount=DEPOSIT,
    )
    out = StringIO()

    call_command("repair_deposit_miscoding", "--unit", "MCG07", "--apply", stdout=out)

    assert "ambiguous" in out.getvalue()
    assert UtilityCharge.objects.filter(pk=charge.pk).exists()
    assert not Payment.objects.filter(payment_type=PaymentType.DEPOSIT).exists()


# --- F9: reclassifying a bare rent payment (no offsetting charge) -----------

def test_reclassify_one_payment_with_no_offsetting_charge(ignite):
    """Production's actual shape: money typed in as rent, nothing to pair it with."""
    payment = process_payment(
        tenant=ignite, amount=DEPOSIT, payment_date=PAY_DATE,
        period_month=8, period_year=2026, source=PaymentSource.BANK,
        reference="FT26236ABCD",
    )
    # The scan finds nothing — there is no charge to match on.
    out = StringIO()
    call_command("repair_deposit_miscoding", "--unit", "MCG07", "--apply", stdout=out)
    assert "Nothing to repair" in out.getvalue()
    payment.refresh_from_db()
    assert payment.voided_at is None

    call_command("repair_deposit_miscoding", "--payment", str(payment.pk), "--apply",
                 stdout=StringIO())

    payment.refresh_from_db()
    assert payment.voided_at is not None
    deposit = Payment.objects.get(tenant=ignite, payment_type=PaymentType.DEPOSIT)
    assert deposit.amount == DEPOSIT
    assert deposit.payment_date == PAY_DATE
    lines = _lines("payment", deposit.pk, "normal")
    assert lines["1030"] == (DEPOSIT, D("0.00"))
    assert lines["2100"] == (D("0.00"), DEPOSIT)
    ignite.refresh_from_db()
    assert ignite.deposit_paid == DEPOSIT


def test_reclassify_preview_writes_nothing(ignite):
    payment = process_payment(
        tenant=ignite, amount=DEPOSIT, payment_date=PAY_DATE,
        period_month=8, period_year=2026, source=PaymentSource.BANK, reference="FT2",
    )
    out = StringIO()
    call_command("repair_deposit_miscoding", "--payment", str(payment.pk), stdout=out)
    assert "DRY RUN" in out.getvalue()
    payment.refresh_from_db()
    assert payment.voided_at is None


def test_reclassify_rejects_an_already_voided_payment(ignite):
    from apps.payments.services import void_payment
    payment = process_payment(
        tenant=ignite, amount=DEPOSIT, payment_date=PAY_DATE,
        period_month=8, period_year=2026, source=PaymentSource.BANK, reference="FT3",
    )
    void_payment(payment, reason="test")
    with pytest.raises(Exception, match="already voided"):
        call_command("repair_deposit_miscoding", "--payment", str(payment.pk), "--apply",
                     stdout=StringIO())
