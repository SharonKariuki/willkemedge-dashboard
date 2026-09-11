"""
Reconcile Fortcom Realtors (MCF01) to the 1 Sept 2026 statement and the payment
that followed it.

Two bank credits make up this tenancy, and both were allocated on a wrong
reading of what they were for.

**10 Aug 2026 — 75,000.** Read as three months' rent and split 25,000 across
August, September and October. It was a 50,000 deposit plus 25,000 of August
rent. The wrong reading raised charges for two months nobody had billed and
left the tenancy looking settled to the end of October.

**5 Sept 2026 — 32,000.** Paid against the 1 Sept statement. FIFO allocated it
across the three periods the first mis-read had created, filling the VAT gap in
each (4,000 + 4,000 + 4,000) and dropping the remaining 20,000 on September. So
a second, correct payment was distributed over charges that should not exist.

This command owns MCF01's whole position: both credits, the charges for August
and September, and the October charge that only the mis-split ever raised.
Everything is derived from the statement plus the one receipt that came after
it, and the run refuses to report success unless the books foot.

What the statement says (as at 1 Sept 2026)
-------------------------------------------
    #  Posting date   Description                Invoice  Payment    Balance
    1  10 Aug 2026    Payment Received                     75,000   (75,000)
    2  10 Aug 2026    Two Months Rent Deposit     50,000            (25,000)
    3  10 Aug 2026    Month Rent - August-2026    25,000                  0
    4  10 Aug 2026    16% VAT on Rent              4,000              4,000
    5  31 Aug 2026    Month Rent - Sept-2026      25,000             29,000
    6  31 Aug 2026    16% VAT on Rent              4,000             33,000

    Arrears / other costs   4,000      (August's VAT, unpaid)
    Current month rent     29,000      (September rent + VAT)
    Total balance due      33,000

Fortcom then paid 32,000 on 5 September — 1,000 short of that total. The
shortfall is small and consistent with a transfer charge deducted at the
tenant's end, but it is real: this reconciliation closes with 1,000 outstanding
on September, and that is the figure to raise with them.

Why 1,000 is also the rent-side balance
---------------------------------------
The statement runs the deposit through the same column as the rent. The books
do not: a deposit is a refundable liability (2100), it is not income, and
``rent_payments_for`` deliberately refuses to let it settle a rent period.

The two still agree, because the deposit invoice and the 50,000 of cash that
paid it cancel out. Strip both and what is left is 58,000 charged against
57,000 of rent received — 1,000, which is also 33,000 stated less 32,000 paid.
``_foot`` checks it both ways round.

October
-------
The October charge exists only because of the mis-split. Under the month-ahead
cycle the biller raises October on 25 September, so until then it is not a real
month and is removed here — but only once the 5 Sept credit has been re-cut off
it, because dropping a charge that cash is sitting against would strand the
payment on a period with nothing to settle.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe.

Usage:
    python manage.py reconcile_fortcom_mcf01
    python manage.py reconcile_fortcom_mcf01 --apply
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


def D(value):
    return Decimal(str(value))


UNIT = "MCF01"
TENANT_ID = 175
TENANT_NAME = "Fortcom Realtors Limited"

STATEMENT_DATE = _dt.date(2026, 9, 1)

RENT = D("25000.00")
VAT = D("4000.00")          # 16% of 25,000, per lines 4 and 6
AUG = (2026, 8)
SEP = (2026, 9)
OCT = (2026, 10)

# Line 2. Two months' rent, agreed — not a part payment of the three-month rule.
DEPOSIT = D("50000.00")
DEPOSIT_MONTHS = 2
DEPOSIT_BASIS = (
    "Two months' rent, per line 2 of the 1 Sept 2026 statement. The commercial "
    "rule is three months; this letting was agreed at two and is paid in full."
)

# Every bank credit on this tenancy, and what each was actually for —
# (reference, date, source, banked, [(amount, payment type, period)], why)
#
# The parts must total the amount banked. A reconciliation redistributes money;
# it must never invent or lose any, and the run refuses if the two disagree.
CREDITS = [
    (
        "S48023247_10082026_2", _dt.date(2026, 8, 10), "bank", D("75000.00"),
        [
            (DEPOSIT, "deposit", AUG),
            (RENT, "rent", AUG),
        ],
        "a 50,000 deposit plus 25,000 August rent, not three months' rent",
    ),
    (
        "CB0289926_05092026_1", _dt.date(2026, 9, 5), "bank", D("32000.00"),
        [
            (D("4000.00"), "rent", AUG),
            (D("28000.00"), "rent", SEP),
        ],
        "paid against the 1 Sept statement: clears August's VAT, then September",
    ),
]

# What the books should charge — (period, rent, VAT).
CHARGES = [
    (AUG, RENT, VAT),
    (SEP, RENT, VAT),
]

# Charges raised by the mis-split alone — (period, why).
DROP = [
    (OCT, "raised by the quarterly mis-split; the biller raises October on 25 Sept"),
]

# The statement's own summary, kept so the footing can be checked a second way.
SUMMARY_ARREARS = D("4000.00")       # August's VAT, unpaid at 1 Sept
SUMMARY_CURRENT = D("29000.00")      # September rent + VAT
TOTAL_DUE = D("33000.00")


def rent_allocated():
    """Cash across all credits that settles rent — the deposit is not income."""
    return sum(
        (amount for _r, _d, _s, _b, parts, _w in CREDITS
         for amount, kind, _p in parts if kind == "rent"),
        D(0),
    )


def charged():
    """The whole obligation the books should carry."""
    return sum((rent + vat for _p, rent, vat in CHARGES), D(0))


def paid_since_the_statement():
    """Cash banked after the statement was cut — what draws its total down."""
    return sum(
        (banked for _r, date, _s, banked, _parts, _w in CREDITS if date > STATEMENT_DATE),
        D(0),
    )


def outstanding():
    """What Fortcom still owes once every credit is where it belongs."""
    return charged() - rent_allocated()


class Command(BaseCommand):
    help = (
        "Reconcile Fortcom Realtors (MCF01) to the 1 Sept 2026 statement and the "
        "32,000 paid on 5 Sept: re-cut both bank credits, record the two-month "
        "deposit agreement, and drop the mis-split's October charge. Dry-run "
        "unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def _head(self, text):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{text}"))

    def _do(self, text):
        self.stdout.write(f"  {text}")
        self.changes += 1

    def _skip(self, text):
        self.stdout.write(self.style.WARNING(f"  skip  {text}"))

    def _note(self, text):
        self.stdout.write(self.style.NOTICE(f"  note  {text}"))

    def handle(self, *args, **opts):
        self.apply = opts["apply"]
        self.changes = 0

        self._check_the_plan()
        tenant = self._preflight()

        self._head("1. The letting")
        self._check_letting(tenant)

        self._head("2. Rent security deposit — what was agreed")
        self._set_agreed_deposit(tenant)

        self._head("3. Bank credits — what each was actually for")
        for ref, date, source, banked, parts, why in CREDITS:
            self._recut(tenant, ref, date, source, banked, parts, why)
        self._report_unknown_credits(tenant)

        self._head("4. Rent security deposit — what was received")
        self._check_deposit_received(tenant)

        self._head("5. Rent charged")
        for period, rent, vat in CHARGES:
            self._set_charge(tenant, period, rent, vat)
        for period, why in DROP:
            self._drop_charge(tenant, period, why)

        self._head("6. Does it foot?")
        self._foot(tenant)

        if not self.apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {self.changes} change(s) would be written. Re-run with --apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nApplied {self.changes} change(s)."))

    # -- pre-flight ---------------------------------------------------------

    def _check_the_plan(self):
        """The figures are transcribed from a PDF and a bank feed. Check they
        hang together before any of them is written."""
        broken = [
            f"{ref}: parts total {sum((a for a, _k, _p in parts), D(0))}, banked {banked}"
            for ref, _d, _s, banked, parts, _w in CREDITS
            if sum((a for a, _k, _p in parts), D(0)) != banked
        ]
        if broken:
            raise CommandError(
                "Pre-flight failed — an allocation does not add up to the money "
                "banked:\n  " + "\n  ".join(broken) + "\n\nNothing was written."
            )

    def _preflight(self):
        """Primary keys are not portable between databases — prove the id first."""
        from apps.tenants.models import Tenant

        tenant = Tenant.objects.filter(pk=TENANT_ID).select_related("unit").first()
        if tenant is None:
            raise CommandError(
                f"Pre-flight failed — tenant #{TENANT_ID} ({TENANT_NAME}) not found. "
                f"Nothing was written."
            )
        actual = tenant.unit.label if tenant.unit else "(no unit)"
        if actual.upper() != UNIT:
            raise CommandError(
                f"Pre-flight failed — #{TENANT_ID} is '{tenant.full_name}' on {actual}, "
                f"the statement says {UNIT}. Primary keys are not portable between "
                f"databases. Nothing was written."
            )
        return tenant

    # -- steps --------------------------------------------------------------

    def _check_letting(self, tenant):
        """Rent and VAT are read, never written — the statement agrees with the
        roll. If they ever stop agreeing that is a change of terms, not a
        reconciliation, so it is reported and left alone."""
        from apps.payments.services import expected_vat_for

        if tenant.monthly_rent != RENT:
            self._skip(
                f"{UNIT} {tenant.full_name}: the roll says rent is {tenant.monthly_rent}, "
                f"the statement says {RENT} — a change of terms, not a reconciliation"
            )
            return
        derived = expected_vat_for(tenant, RENT)
        if derived != VAT:
            self._skip(
                f"{UNIT} {tenant.full_name}: VAT on {RENT} derives to {derived}, the "
                f"statement charges {VAT} — check the unit is still BUSINESS-classified"
            )
            return
        self.stdout.write(f"  {UNIT} {tenant.full_name}: {RENT} + {VAT} VAT a month")

    def _set_agreed_deposit(self, tenant):
        """Record the two-month agreement, so the three-month rule stops
        reporting a shortfall against money nobody owes."""
        from apps.tenants.deposits import deposit_shortfall, expected_deposit

        if tenant.agreed_deposit == DEPOSIT:
            self._skip(f"{UNIT}: deposit already agreed at {DEPOSIT} ({DEPOSIT_MONTHS} months)")
            return

        was = expected_deposit(tenant)
        shortfall = deposit_shortfall(tenant)
        self._do(
            f"{UNIT}: deposit held against {was} -> {DEPOSIT} "
            f"({DEPOSIT_MONTHS} x {RENT}), retiring a reported shortfall of {shortfall}"
        )
        if self.apply:
            tenant.agreed_deposit = DEPOSIT
            tenant.notes = (
                f"{tenant.notes}\nDeposit agreed at {DEPOSIT_MONTHS} months' rent "
                f"({DEPOSIT}): {DEPOSIT_BASIS}"
            ).strip()
            tenant.save(update_fields=["agreed_deposit", "notes", "updated_at"])

    def _recut(self, tenant, ref, date, source, banked, parts, why):
        """Void every live row under a bank reference and re-book it as ``parts``.

        Keyed on the reference rather than a payment id, so it finds whatever a
        previous wrong reading left behind — three monthly rows from a split
        that assumed quarterly rent, or four FIFO chunks spread over periods
        that should not exist.

        Payments are immutable financial records. The correction is a void plus
        a replacement, never an edit, so the original receipt, its mirror-image
        reversal and the corrected rows all stay in the ledger.
        """
        from apps.payments.models import Payment
        from apps.payments.services import process_payment, void_payment

        live = list(Payment.objects.filter(
            tenant=tenant, reference=ref, voided_at__isnull=True,
        ).order_by("pk"))

        already = {(p.amount, p.period_year, p.period_month, p.payment_type) for p in live}
        target = {(amount, year, month, kind) for amount, kind, (year, month) in parts}
        if already == target:
            self._skip(f"{ref}: already booked as {len(parts)} part(s)")
            return
        if not live:
            self._skip(f"{ref}: nothing live under this reference")
            return

        held = sum((p.amount for p in live), D(0))
        if held != banked:
            self._skip(
                f"{ref}: holds {held} but the statement says {banked} was banked — "
                f"refusing to change the amount received"
            )
            return

        was = ", ".join(f"{p.amount} {p.payment_type} {p.period_month}/{p.period_year}" for p in live)
        now = ", ".join(f"{a} {k} {m}/{y}" for a, k, (y, m) in parts)
        self._do(f"{ref} {banked}: [{was}] -> [{now}]  ({why})")
        if not self.apply:
            return
        with transaction.atomic():
            for pay in live:
                void_payment(pay, reason=f"Re-allocated — {why}"[:255])
            for amount, kind, (year, month) in parts:
                process_payment(
                    tenant=tenant, amount=amount, payment_date=date,
                    period_month=month, period_year=year, source=source,
                    reference=ref, idempotency_key=f"{ref}#{kind}-{year}-{month:02d}",
                    payment_type=kind,
                    notes=f"Re-allocated by reconcile_fortcom_mcf01: {why}.",
                )

    def _report_unknown_credits(self, tenant):
        """Name any money this command does not know about.

        The footing check would catch an unexpected receipt, but only as a
        number that does not tie. Naming the reference turns 'it does not
        balance' into 'this credit arrived after the plan was written'.
        """
        from apps.payments.models import Payment

        known = {ref for ref, _d, _s, _b, _p, _w in CREDITS}
        strangers = (
            Payment.objects.filter(tenant=tenant, voided_at__isnull=True)
            .exclude(reference__in=known)
            .order_by("payment_date", "pk")
        )
        for pay in strangers:
            self._note(
                f"{pay.payment_date} {pay.amount} {pay.payment_type} "
                f"{pay.period_month}/{pay.period_year} under "
                f"'{pay.reference or '(no reference)'}' — arrived after this "
                f"reconciliation was written, and is not allocated by it"
            )

    def _check_deposit_received(self, tenant):
        """Reconcile ``deposit_paid`` to the deposit actually banked."""
        from apps.payments.models import Payment, PaymentType

        live = Payment.objects.filter(
            tenant=tenant, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True,
        )
        banked = sum((p.amount for p in live), D(0))

        if banked != DEPOSIT:
            self._skip(
                f"{UNIT}: {banked} of deposit payments on record, the statement says "
                f"{DEPOSIT} — leaving deposit_paid alone until the credits are re-cut"
            )
            return
        if tenant.deposit_paid == DEPOSIT:
            self._skip(f"{UNIT}: {DEPOSIT} received and recorded")
            return

        self._do(f"{UNIT}: deposit received {tenant.deposit_paid} -> {DEPOSIT}")
        if self.apply:
            tenant.deposit_paid = DEPOSIT
            tenant.save(update_fields=["deposit_paid", "updated_at"])

    def _set_charge(self, tenant, period, rent, vat):
        """Raise or correct one period's rent and VAT, then let the canonical
        routine re-derive what is paid and what is left."""
        from apps.payments.models import Arrears
        from apps.payments.services import _update_arrears

        year, month = period
        arr = Arrears.objects.filter(
            tenant=tenant, period_year=year, period_month=month
        ).first()
        if arr and (arr.expected_rent, arr.expected_vat) == (rent, vat):
            self._skip(f"{UNIT}: {month}/{year} already {rent} + {vat} VAT")
            return

        was = f"{arr.expected_rent} + {arr.expected_vat} VAT" if arr else "not billed"
        self._do(f"{UNIT}: {month}/{year} {was} -> {rent} + {vat} VAT")
        if not self.apply:
            return
        with transaction.atomic():
            if arr:
                Arrears.objects.filter(pk=arr.pk).update(expected_rent=rent, expected_vat=vat)
            else:
                Arrears.objects.create(
                    tenant=tenant, period_year=year, period_month=month,
                    expected_rent=rent, expected_vat=vat, amount_paid=D(0),
                    balance=rent + vat, is_cleared=False,
                )
            _update_arrears(tenant, month, year)

    def _drop_charge(self, tenant, period, why):
        """Remove a charge the mis-split raised and nothing else justifies.

        Guarded twice, exactly as in ``apply_matasia_answers``: not while cash
        sits against the period, and not once the billing cycle has reached it.
        A mis-split leftover and a genuinely billed month are the same row, so
        the calendar is the only thing that tells them apart — and past that
        point ``generate_monthly_arrears`` would raise it straight back.
        """
        from apps.payments.billing_calendar import tenant_billing_period
        from apps.payments.models import Arrears, Payment

        year, month = period
        charge = Arrears.objects.filter(
            tenant=tenant, period_year=year, period_month=month
        ).first()
        if charge is None:
            self._skip(f"{UNIT}: no charge for {month}/{year}")
            return

        billing = tenant_billing_period(tenant)
        if period <= billing:
            self._skip(
                f"{UNIT}: the cycle is billing {billing[1]}/{billing[0]}, so {month}/{year} "
                f"is a month the biller now raises — refusing to drop a charge that "
                f"generate_monthly_arrears would put straight back"
            )
            return

        held = Payment.objects.filter(
            tenant=tenant, period_year=year, period_month=month, voided_at__isnull=True,
        ).count()
        if held:
            self._skip(
                f"{UNIT}: {month}/{year} still holds {held} payment(s) — not removing a "
                f"charge that cash is sitting against; re-cut the credits first"
            )
            return

        self._do(
            f"{UNIT}: drop {month}/{year} charge of "
            f"{charge.expected_rent + charge.expected_vat}  ({why})"
        )
        if self.apply:
            charge.delete()

    def _foot(self, tenant):
        """Print the position back from the books and say whether it ties."""
        from apps.payments.models import Arrears

        self.stdout.write(f"      {'period':<10}{'charged':>12}{'paid':>12}{'balance':>12}")
        total = D(0)
        gaps = []
        for period, _rent, _vat in CHARGES:
            year, month = period
            arr = Arrears.objects.filter(
                tenant=tenant, period_year=year, period_month=month
            ).first()
            if arr is None:
                self.stdout.write(
                    f"      {month:02d}/{year:<7}{'not billed':>12}{'':>12}{'':>12}"
                )
                gaps.append(f"{month}/{year} is not billed")
                continue
            self.stdout.write(
                f"      {month:02d}/{year:<7}{arr.expected_rent + arr.expected_vat:>12,.2f}"
                f"{arr.amount_paid:>12,.2f}{arr.balance:>12,.2f}"
            )
            total += arr.balance

        for period, _why in DROP:
            year, month = period
            if Arrears.objects.filter(
                tenant=tenant, period_year=year, period_month=month
            ).exists():
                gaps.append(f"{month}/{year} is still charged")

        self.stdout.write(f"      {'':<10}{'':>12}{'':>12}{'-' * 12:>12}")
        self.stdout.write(f"      {'total':<10}{'':>12}{'':>12}{total:>12,.2f}")
        self.stdout.write(
            f"      deposit held separately: {tenant.deposit_paid:,.2f} "
            f"(a 2100 liability, outside the rent balance)"
        )

        want = outstanding()
        if gaps or total != want:
            detail = "; ".join(gaps) or f"the periods sum to {total}, expected {want}"
            when = "the books do not yet show" if not self.apply else "does not reconcile to"
            self._note(f"{when} {want:,.2f} outstanding — {detail}")
            if self.apply:
                raise CommandError(
                    f"Reconciliation did not foot to {want}. The changes above were "
                    f"written; investigate before relying on the rent roll for {UNIT}."
                )
            return

        self.stdout.write(self.style.SUCCESS(
            f"  reconciles: {TOTAL_DUE:,.2f} due on the {STATEMENT_DATE:%d %b %Y} statement, "
            f"less {paid_since_the_statement():,.2f} paid since, leaves {want:,.2f} owing"
        ))
        if want:
            self._note(
                f"{UNIT} {tenant.full_name} is {want:,.2f} short of the statement — small "
                f"enough to be a transfer charge deducted at their end, but it is real "
                f"and someone has to ask them"
            )
