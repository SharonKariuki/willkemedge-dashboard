"""
Restart tenants' books on the landlord's end-of-month balance.

    python manage.py set_opening_balances ~/Downloads/opening_balances_matasia_2026_08_31.csv \\
        --as-of 2026-08-31 --source "Matasia sheet as on 16 Sept 2026"
    python manage.py set_opening_balances <file> --as-of 2026-08-31 --source "…" --apply
    python manage.py set_opening_balances <file> --undo --apply

The landlord's sheets are the record the business agrees to. This gives each
tenant on the sheet one ``OpeningBalance`` — the sheet's balance on ``--as-of``
— and from then on everything dated on or before that day is history: kept,
never deleted, counted nowhere (see ``apps.payments.books``). Nothing outside
the file is touched, so a building moves over only when its sheet is loaded.

Keep the sheet files out of the repository: they are tenant balances.

The file is a CSV with a header row:

  unit         the unit label (MR302, MCG05 …) of a current tenant
  opening      balance on --as-of: positive owed, negative in credit
  deposit      optional — deposit held per the sheet. "Sheet wins": the books
               are brought to it through 2100. A deposit lowered from money
               the tenant actually paid is not lost: the excess is re-booked as
               rent, on the same date and reference as the payment it came in.
               A deposit that was only a booking (``sync_deposit_bookings``, a
               director's edit) had no money behind it and is simply lowered.
  first_other  optional — the water and other costs on the first invoice in
               the books (the sheet's "Other costs" for that month). Any
               difference from what the app already carries for that invoice
               is posted as one adjusting charge.
  check_date   optional, with check_balance — a later sheet's balance on that
  check_balance  date (e.g. the 7 Oct sheet's unpaid balance). Reported, never
               acted on: it is how a restart is verified against the next sheet.

Every run happens inside a transaction. A dry run (the default) rolls it back
after reporting exactly what the apply would leave behind; ``--apply`` keeps
it. It is idempotent: a second run against the same file changes nothing.

``--undo`` deletes the OpeningBalance rows for the units in the file, which
puts those tenants back on their full history (their ledger entries reverse).
Deposit bookings and adjusting charges are left: they are ordinary records,
and are reversed the ordinary way if needed.
"""
from __future__ import annotations

import csv
import datetime as _dt
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")
ADJUSTMENT_LABEL = "Other costs - sheet adjustment"


class _DryRun(Exception):
    pass


def _is_booking_only(payment) -> bool:
    """A deposit row the app posted to match a figure, not money received."""
    notes = payment.notes or ""
    return "sync_deposit_bookings" in notes or notes.startswith("Deposit edited")


def _money(raw: str, *, field: str, line: int) -> Decimal | None:
    raw = (raw or "").replace(",", "").strip()
    if raw == "":
        return None
    try:
        return Decimal(raw).quantize(CENTS)
    except InvalidOperation as exc:
        raise CommandError(f"Line {line}: {field} {raw!r} is not a number.") from exc


def _date(raw: str, *, field: str, line: int | None = None) -> _dt.date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return _dt.date.fromisoformat(raw)
    except ValueError as exc:
        where = f"Line {line}: " if line else ""
        raise CommandError(f"{where}{field} {raw!r} is not a YYYY-MM-DD date.") from exc


def _read(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            missing = {"unit", "opening"} - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"{path} is missing column(s): {', '.join(sorted(missing))}")
            rows = []
            for line, row in enumerate(reader, start=2):
                unit = (row.get("unit") or "").strip()
                if not unit:
                    continue
                opening = _money(row.get("opening"), field="opening", line=line)
                if opening is None:
                    raise CommandError(f"Line {line}: {unit} has no opening balance.")
                rows.append({
                    "line": line,
                    "unit": unit,
                    "opening": opening,
                    "deposit": _money(row.get("deposit"), field="deposit", line=line),
                    "first_other": _money(row.get("first_other"), field="first_other", line=line),
                    "check_date": _date(row.get("check_date"), field="check_date", line=line),
                    "check_balance": _money(row.get("check_balance"), field="check_balance", line=line),
                })
            return rows
    except FileNotFoundError as exc:
        raise CommandError(f"No such file: {path}") from exc


class Command(BaseCommand):
    help = "Restart tenants' books on the landlord's end-of-month balance (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="CSV: unit, opening[, deposit, first_other, check_date, check_balance]")
        parser.add_argument("--as-of", help="Last day before the books begin, e.g. 2026-08-31.")
        parser.add_argument("--source", default="", help="Where the figures came from (kept on each row).")
        parser.add_argument("--apply", action="store_true", help="Keep the changes (default: dry run).")
        parser.add_argument("--undo", action="store_true", help="Remove the opening balances for these units.")

    def handle(self, *args, **opts):
        rows = _read(opts["file"])
        if not rows:
            raise CommandError("The file lists no units.")
        apply = opts["apply"]
        self.stdout.write(("APPLYING" if apply else "DRY RUN — nothing is saved") + f": {opts['file']}")

        try:
            with transaction.atomic():
                if opts["undo"]:
                    self._undo(rows)
                else:
                    as_of = _date(opts["as_of"], field="--as-of")
                    if as_of is None:
                        raise CommandError("--as-of is required.")
                    if (as_of + _dt.timedelta(days=1)).day != 1:
                        raise CommandError("--as-of must be the last day of a month.")
                    if not opts["source"].strip():
                        raise CommandError("--source is required: say which sheet the figures came from.")
                    problems = self._restart(rows, as_of=as_of, source=opts["source"].strip())
                    if problems and apply:
                        raise CommandError(
                            f"{problems} unit(s) could not be restarted (above); nothing was saved."
                        )
                if not apply:
                    raise _DryRun
        except _DryRun:
            self.stdout.write(self.style.WARNING("Dry run rolled back. Re-run with --apply to keep it."))
            return
        self.stdout.write(self.style.SUCCESS("Applied."))

    # ── helpers ──────────────────────────────────────────────────────────────

    def _tenant_for(self, label: str):
        from apps.tenants.models import CURRENT_STATUSES, Tenant

        tenants = list(
            Tenant.objects.filter(unit__label__iexact=label, status__in=CURRENT_STATUSES)
            .select_related("unit__building")
        )
        if len(tenants) != 1:
            raise CommandError(
                f"{label}: expected one current tenant, found {len(tenants)}. "
                "Register or move out the tenant first, then re-run."
            )
        return tenants[0]

    def _undo(self, rows):
        from apps.payments.models import OpeningBalance

        for row in rows:
            ob = OpeningBalance.objects.filter(tenant__unit__label__iexact=row["unit"]).first()
            if ob is None:
                self.stdout.write(f"  {row['unit']:<7} no opening balance — nothing to undo")
                continue
            self.stdout.write(f"  {row['unit']:<7} removing opening KES {ob.amount:,.2f} at {ob.as_of}")
            ob.delete()

    def _restart(self, rows, *, as_of, source):
        from apps.payments import books
        from apps.payments.models import OpeningBalance
        from apps.payments.monthly_ledger import current_balance
        from apps.tenants.deposits import deposit_held_on_books

        today = _dt.date.today()
        mismatches = problems = 0
        for row in rows:
            try:
                tenant = self._tenant_for(row["unit"])
            except CommandError as exc:
                problems += 1
                self.stdout.write(self.style.ERROR(f"  {exc}"))
                continue
            label = f"{row['unit']:<7} {tenant.full_name[:28]:<28}"
            balance_before = current_balance(tenant, today=today)
            deposit_before = deposit_held_on_books(tenant)

            ob, created = OpeningBalance.objects.get_or_create(
                tenant=tenant,
                defaults={"as_of": as_of, "amount": row["opening"], "source": source},
            )
            if not created and (ob.as_of, ob.amount, ob.source) != (as_of, row["opening"], source):
                ob.as_of, ob.amount, ob.source = as_of, row["opening"], source
                ob.save()

            notes = []
            if row["first_other"] is not None:
                notes.append(self._first_other(tenant, ob, row["first_other"]))
            if row["deposit"] is not None and row["deposit"] != deposit_before:
                notes.append(self._deposit(tenant, row["deposit"], as_of=as_of))

            changed = books.resettle(tenant)
            if changed:
                notes.append(f"{len(changed)} open month(s) resettled")

            balance_after = current_balance(tenant, today=today)
            self.stdout.write(
                f"  {label} opening {row['opening']:>12,.2f} | balance now "
                f"{balance_before:>12,.2f} -> {balance_after:>12,.2f} | deposit "
                f"{deposit_before:>10,.2f} -> {deposit_held_on_books(tenant):>10,.2f}"
            )
            for note in filter(None, notes):
                self.stdout.write(f"      {note}")

            if row["check_date"] and row["check_balance"] is not None:
                got = self._balance_on(tenant, row["check_date"])
                ok = got == row["check_balance"]
                mismatches += not ok
                style = self.style.SUCCESS if ok else self.style.ERROR
                self.stdout.write(style(
                    f"      check {row['check_date']}: app {got:,.2f} vs sheet "
                    f"{row['check_balance']:,.2f}" + ("" if ok else f" (off by {got - row['check_balance']:,.2f})")
                ))
        if mismatches:
            self.stdout.write(self.style.ERROR(f"{mismatches} unit(s) do not match the check sheet."))
        return problems

    def _balance_on(self, tenant, day: _dt.date) -> Decimal:
        """The statement's closing balance as at ``day`` — what a sheet of that date shows."""
        from apps.payments.statement_service import _build_ledger

        _rows, balance, _bf = _build_ledger(tenant, as_of=day)
        return Decimal(balance).quantize(CENTS)

    def _first_other(self, tenant, ob, target: Decimal) -> str:
        """Bring the first invoice's water and other costs to the sheet's figure."""
        from apps.payments import books
        from apps.payments.meter_service import invoiced_with
        from apps.payments.models import UtilityCharge

        books_from = ob.books_from
        adjustment = UtilityCharge.objects.filter(
            tenant=tenant, label=ADJUSTMENT_LABEL,
            period_year=ob.books_year, period_month=ob.books_month,
        ).first()
        carried = sum(
            (Decimal(u.amount) for u in UtilityCharge.objects.filter(tenant=tenant)
             .filter(books.utilities_q())
             if invoiced_with(u) == books_from and (adjustment is None or u.pk != adjustment.pk)),
            ZERO,
        )
        needed = (target - carried).quantize(CENTS)
        if needed == ZERO:
            if adjustment is not None:
                adjustment.delete()
                return f"first invoice other costs {carried:,.2f} already match — adjustment removed"
            return None
        if adjustment is None:
            UtilityCharge.objects.create(
                tenant=tenant, label=ADJUSTMENT_LABEL, amount=needed,
                posting_date=books_from, period_year=ob.books_year, period_month=ob.books_month,
            )
        elif adjustment.amount != needed:
            adjustment.amount = needed
            adjustment.save()
        else:
            return None
        return f"first invoice other costs {carried:,.2f} -> {target:,.2f} (adjustment {needed:,.2f})"

    def _deposit(self, tenant, target: Decimal, *, as_of) -> str:
        """Bring the deposit held to the sheet, keeping any excess as rent paid."""
        from apps.payments.models import Payment, PaymentType
        from apps.payments.services import process_payment
        from apps.tenants.deposits import deposit_held_on_books
        from apps.tenants.services import DepositAdjustmentError, adjust_deposit_held

        before = deposit_held_on_books(tenant)
        live_before = set(
            Payment.objects.filter(
                tenant=tenant, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True
            ).values_list("pk", flat=True)
        )
        try:
            adjust_deposit_held(tenant, target, on=as_of)
        except DepositAdjustmentError as exc:
            return f"DEPOSIT NOT CHANGED: {exc}"
        if target >= before:
            return f"deposit raised to the sheet's {target:,.2f}"

        # Lowered. A deposit that was only ever a booking — the tenant card's
        # figure posted by ``sync_deposit_bookings`` or a director's edit — had
        # no money behind it, so lowering it loses nothing. Money the tenant
        # actually sent as deposit is now rent they paid.
        voided = Payment.objects.filter(pk__in=live_before, voided_at__isnull=False).order_by("payment_date")
        excess = before - target
        rebooked = []
        for pay in voided:
            if excess <= ZERO:
                break
            if _is_booking_only(pay):
                excess -= min(pay.amount, excess)
                continue
            replacement = Payment.objects.filter(
                tenant=tenant, payment_type=PaymentType.DEPOSIT, voided_at__isnull=True,
                payment_date=pay.payment_date, reference=pay.reference,
            ).exclude(pk__in=live_before)
            kept = sum((p.amount for p in replacement), ZERO)
            amount = min(pay.amount - kept, excess)
            if amount <= ZERO:
                continue
            process_payment(
                tenant=tenant, amount=amount, payment_date=pay.payment_date,
                period_month=pay.payment_date.month, period_year=pay.payment_date.year,
                source=pay.source, reference=pay.reference,
                notes=f"Deposit restated to the landlord sheet's {target:,.2f}; "
                      f"this part of payment #{pay.pk} was rent.",
                payment_type=PaymentType.RENT,
            )
            rebooked.append(f"{amount:,.2f} of #{pay.pk}")
            excess -= amount
        return (
            f"deposit lowered to the sheet's {target:,.2f}; re-booked as rent: "
            + (", ".join(rebooked) or "nothing (the excess was a booking, not money received)")
        )
