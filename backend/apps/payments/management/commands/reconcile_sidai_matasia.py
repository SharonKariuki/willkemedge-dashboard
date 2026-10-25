"""
Bring Sidai Lonestar Healthcare into line with the 7 Oct 2026 statement.

One command owns Sidai's whole position across its two tenant records, because
one bank credit pays both and re-allocating it piecemeal is how the Fortcom
reconciliation went circular. Three things, in order:

  1. the 14 Sept credit, split between the two lettings as the sheets read it;
  2. MCG06 joins MCG05's space from October, at 86,500 + 20,000 = 106,500;
  3. October charged as the 7 Oct sheet bills it — MCG05 123,540, MCF12 58,760.

The 14 Sept credit
------------------
Sidai Lonestar Healthcare pays for two lettings with one transfer: the ground
floor (MCG05) and the first-floor office (MCF12, tenant "Sidai Healthcare
Residential"). The 14 Sept credit of 161,480 was assigned from the unmatched
queue to MCG05 alone, in two FIFO chunks — 98,080 against July and 63,400
against September. The landlord's 16 Sept 2026 status sheet reads it as two
payments:

    MCG05  102,720  = B/F 180 + Sept rent 86,500 + VAT 13,840 + other 2,200
    MCF12   58,760  = Sept rent 50,655 + VAT 8,105

so MCG05 closed September at nil and MCF12 kept only the 10,000 brought forward
from July. With the whole credit on MCG05 the app showed the reverse: MCG05
58,420 in credit and MCF12 owing September in full.

The cut moves only what is wrong. The 98,080 chunk on MCG05's July is left
exactly as it is — that July row is a separate question, held back from
``repair_matasia_july_rebill`` because of the 15 July receipt. The 63,400 chunk
is voided and re-booked as the 4,640 of it that is MCG05's September plus the
58,760 that is MCF12's. Payments are immutable: a void plus replacements, never
an edit, so the original receipt and its reversal stay in the ledger.

MCF12's September VAT was raised at 8,104.80; August's is 8,105 and so is the
sheet's. It is restated to 8,105 so the receipt clears the month exactly
rather than leaving 0.20 of credit.

October
-------
The 7 Oct sheet bills MCG05 at 106,500 + VAT — its own 86,500 plus MCG06 at
20,000, one tenancy over two units — and keeps MCF12 on its own line at 58,760
while Sidai moves out of it. MCG06 is added to MCG05's combined space through
``reconfigure_space``, which sets the rent the biller uses from November;
October was already raised at 86,500 on 25 Sept, so its row is restated here.
MCF12's October was never raised (the tenant is on notice), so it is raised.

The 14 Oct credit of 126,340 is the sheet's MCG05 figure to the shilling and
already sits on MCG05's October; it is not touched.

Not done here: MCG05's 2,800 water on the 7 Oct sheet is a meter reading, and
the September reading for MCG05 is not in the app. It belongs on the meter
chain, not in a flat charge. MCG08 and MCG09 join the space when a sheet first
bills them.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe.

Usage:
    python manage.py reconcile_sidai_matasia
    python manage.py reconcile_sidai_matasia --apply
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


def D(value):
    return Decimal(str(value))


REF = "CB0526926_14092026_1"
DATE = _dt.date(2026, 9, 14)
BANKED = D("161480.00")
JUL = (2026, 7)
SEP = (2026, 9)
SHEET_DATE = _dt.date(2026, 9, 16)

# (key, tenant id, unit label) — ids are checked against the label before use.
MCG05 = ("MCG05", 148, "MCG05")
MCF12 = ("MCF12", 166, "MCF12")
TENANCIES = (MCG05, MCF12)

# What the credit should be, row for row — (tenancy key, amount, period).
TARGET = [
    ("MCG05", D("98080.00"), JUL),
    ("MCG05", D("4640.00"), SEP),
    ("MCF12", D("58760.00"), SEP),
]

# MCF12 September, restated to the sheet's figure.
MCF12_SEP_VAT = D("8105.00")

# What the 16 Sept sheet says each tenancy owed once the credit landed.
SHEET_UNPAID = {"MCG05": D("0.00"), "MCF12": D("10000.00")}

OCT = (2026, 10)
OCT_SHEET_DATE = _dt.date(2026, 10, 7)

# MCG05's combined space from October — (member label, its share of the rent).
SPACE_MEMBERS = [("MCG06", D("20000.00"))]
MCG05_OWN_RENT = D("86500.00")
SPACE_RENT = MCG05_OWN_RENT + sum((r for _l, r in SPACE_MEMBERS), D(0))

# October as the 7 Oct sheet bills it — tenancy key -> (rent, VAT).
OCTOBER = {
    "MCG05": (SPACE_RENT, D("17040.00")),
    "MCF12": (D("50655.00"), D("8105.00")),
}

# What the 7 Oct sheet says each owed, and what of that this command leaves out.
OCT_SHEET_UNPAID = {"MCG05": D("126340.00"), "MCF12": D("68760.00")}
OCT_NOT_HERE = {"MCG05": (D("2800.00"), "water: September meter reading not in the app")}


class Command(BaseCommand):
    help = (
        "Bring Sidai (MCG05 + MCF12) into line with the 7 Oct 2026 statement: split "
        "the 14 Sept credit, add MCG06 to MCG05's space, charge October as the sheet "
        "does. Dry-run unless --apply."
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

        if sum((amount for _k, amount, _p in TARGET), D(0)) != BANKED:
            raise CommandError("Pre-flight failed — the split does not add up to the credit. Nothing was written.")
        tenants = self._preflight()

        self._head("1. MCF12 September VAT")
        self._restate_mcf12_vat(tenants["MCF12"])

        self._head(f"2. {REF} {BANKED:,.2f} — one credit, two tenancies")
        self._recut(tenants)

        self._head("3. Does September foot? (16 Sept sheet)")
        self._foot(tenants)

        self._head("4. MCG05's space from October")
        self._combine_space(tenants["MCG05"])

        self._head("5. October charged as the 7 Oct sheet bills it")
        for key, (rent, vat) in OCTOBER.items():
            self._set_october(key, tenants[key], rent, vat)

        self._head("6. Does October foot? (7 Oct sheet)")
        self._foot_october(tenants)

        if not self.apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {self.changes} change(s) would be written. Re-run with --apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nApplied {self.changes} change(s)."))

    def _preflight(self):
        """Primary keys are not portable between databases — prove each id first."""
        from apps.tenants.models import Tenant

        found = {}
        for key, tid, label in TENANCIES:
            tenant = Tenant.objects.filter(pk=tid).select_related("unit").first()
            actual = tenant.unit.label if tenant and tenant.unit else None
            if actual is None or actual.upper() != label:
                raise CommandError(
                    f"Pre-flight failed — tenant #{tid} is not on {label} "
                    f"({actual or 'not found'}). Primary keys are not portable between "
                    f"databases. Nothing was written."
                )
            found[key] = tenant
        return found

    def _restate_mcf12_vat(self, tenant):
        from apps.payments.models import Arrears

        year, month = SEP
        arr = Arrears.objects.filter(tenant=tenant, period_year=year, period_month=month).first()
        if arr is None:
            self._skip("MCF12: September is not billed — nothing to restate")
            return
        if arr.expected_vat == MCF12_SEP_VAT:
            self._skip(f"MCF12: September VAT already {MCF12_SEP_VAT}")
            return
        self._do(f"MCF12: September VAT {arr.expected_vat} -> {MCF12_SEP_VAT} (as August and the sheet)")
        if self.apply:
            # .save(), not .update(): the accrual ledger posts the charge off
            # the Arrears post_save signal, and an update would leave 2600 at
            # the old VAT.
            from apps.payments.services import _update_arrears

            with transaction.atomic():
                arr.expected_vat = MCF12_SEP_VAT
                arr.save(update_fields=["expected_vat"])
                _update_arrears(tenant, month, year)

    def _recut(self, tenants):
        """Void the live rows the target does not contain; book the ones it lacks.

        Matched on (tenancy, amount, period), so a re-run finds the target
        already in place and writes nothing.
        """
        from apps.payments.models import Payment
        from apps.payments.services import process_payment, void_payment

        by_pk = {t.pk: key for key, t in tenants.items()}
        live = list(Payment.objects.filter(
            tenant__in=tenants.values(), reference=REF, voided_at__isnull=True,
        ).order_by("pk"))

        held = sum((p.amount for p in live), D(0))
        if held != BANKED:
            self._skip(
                f"{REF}: live rows hold {held}, the bank credited {BANKED} — refusing to "
                f"change the amount received"
            )
            return

        wanted = list(TARGET)
        stale = []
        for pay in live:
            row = (by_pk[pay.tenant_id], pay.amount, (pay.period_year, pay.period_month))
            if row in wanted:
                wanted.remove(row)
                self._skip(f"{row[0]} {pay.amount} {pay.period_month}/{pay.period_year}: already right")
            else:
                stale.append(pay)

        if not stale and not wanted:
            return
        for pay in stale:
            self._do(f"void  {by_pk[pay.tenant_id]} {pay.amount} {pay.period_month}/{pay.period_year}")
        for key, amount, (year, month) in wanted:
            self._do(f"book  {key} {amount} {month}/{year}")
        if not self.apply:
            return

        why = "Sidai's 14 Sept credit split between MCG05 and MCF12 per the 16 Sept 2026 status sheet"
        with transaction.atomic():
            for pay in stale:
                void_payment(pay, reason=f"Re-allocated — {why}"[:255])
            for key, amount, (year, month) in wanted:
                process_payment(
                    tenant=tenants[key], amount=amount, payment_date=DATE,
                    period_month=month, period_year=year, source="bank",
                    reference=REF, idempotency_key=f"{REF}#{key}-{year}-{month:02d}",
                    payment_type="rent",
                    notes=f"Re-allocated by reconcile_sidai_matasia: {why}.",
                )

    def _foot(self, tenants):
        """Read each tenancy's balance back off the statement as at the sheet date."""
        from apps.payments.statement_service import build_statement

        ok = True
        for key, tenant in tenants.items():
            s = build_statement(tenant, statement_date=SHEET_DATE, as_of=SHEET_DATE)
            have, want = s["total_due_value"], SHEET_UNPAID[key]
            line = f"{key} unpaid at {SHEET_DATE:%d %b}: app {have:,.2f}, sheet {want:,.2f}"
            if have == want:
                self.stdout.write(self.style.SUCCESS(f"  ties  {line}"))
            else:
                ok = False
                self._note(f"{line} — differs by {have - want:,.2f}")
        if self.apply and not ok:
            self._note(
                "The credit is split as the sheet reads it; any difference left is in "
                "the charges, not this receipt."
            )

    def _combine_space(self, head_tenant):
        from apps.buildings.models import Unit
        from apps.buildings.spaces import reconfigure_space

        head = head_tenant.unit
        labels = [label for label, _r in SPACE_MEMBERS]
        members = list(Unit.objects.filter(building=head.building, label__in=labels))
        if len(members) != len(labels):
            missing = set(labels) - {u.label for u in members}
            self._skip(f"MCG05: {', '.join(sorted(missing))} not found in {head.building.name}")
            return
        add = [u for u in members if u.combined_into_id != head.pk]
        if not add and head_tenant.monthly_rent == SPACE_RENT:
            self._skip(f"MCG05: space already {head.space_label} at {SPACE_RENT}")
            return
        self._do(
            f"MCG05: add {', '.join(u.label for u in add) or '(none)'} to the space; "
            f"rent {head_tenant.monthly_rent} -> {SPACE_RENT}"
        )
        if not self.apply:
            return
        with transaction.atomic():
            if add:
                reconfigure_space(head, add=add, monthly_rent=SPACE_RENT)
            else:
                head_tenant.monthly_rent = SPACE_RENT
                head_tenant.save(update_fields=["monthly_rent", "updated_at"])
        head_tenant.refresh_from_db()

    def _set_october(self, key, tenant, rent, vat):
        """Raise or restate October — ``.save()``/``create`` so the ledger posts."""
        from apps.payments.models import Arrears
        from apps.payments.services import _update_arrears

        year, month = OCT
        arr = Arrears.objects.filter(tenant=tenant, period_year=year, period_month=month).first()
        if arr and (arr.expected_rent, arr.expected_vat) == (rent, vat):
            self._skip(f"{key}: October already {rent} + {vat} VAT")
            return
        was = f"{arr.expected_rent} + {arr.expected_vat} VAT" if arr else "not billed"
        self._do(f"{key}: October {was} -> {rent} + {vat} VAT = {rent + vat}")
        if not self.apply:
            return
        with transaction.atomic():
            if arr:
                arr.expected_rent, arr.expected_vat = rent, vat
                arr.save(update_fields=["expected_rent", "expected_vat"])
            else:
                Arrears.objects.create(
                    tenant=tenant, period_year=year, period_month=month,
                    expected_rent=rent, expected_vat=vat, amount_paid=D(0),
                    balance=rent + vat, is_cleared=False,
                )
            _update_arrears(tenant, month, year)

    def _foot_october(self, tenants):
        from apps.payments.statement_service import build_statement

        for key, tenant in tenants.items():
            s = build_statement(tenant, statement_date=OCT_SHEET_DATE, as_of=OCT_SHEET_DATE)
            have = s["total_due_value"]
            left_out, why = OCT_NOT_HERE.get(key, (D(0), ""))
            want = OCT_SHEET_UNPAID[key] - left_out
            line = (
                f"{key} unpaid at {OCT_SHEET_DATE:%d %b}: app {have:,.2f}, sheet "
                f"{OCT_SHEET_UNPAID[key]:,.2f}"
                + (f" less {left_out:,.2f} {why}" if left_out else "")
            )
            if have == want:
                self.stdout.write(self.style.SUCCESS(f"  ties  {line}"))
            else:
                self._note(f"{line} — differs by {have - want:,.2f}")
