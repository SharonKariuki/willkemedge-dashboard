"""
Take the non-rent properties off the rent roll and bring their balances to nil.

Five occupancies are on the books but are not lettings, on the landlord's
instruction of 14 Nov 2026. They are not charged rent; they only attract
expenses and other income:

    FMNCH  Wilkem Farm, Mwongori Nyamira       caretaker
    FNNCH  Wilkem Farm, Nyariacho Nyamira      caretaker
    FSCH   Wilkem Navillus Farm, Soy Eldoret   caretaker
    KNCH   Wilkem Residence, The Baobab Karen  caretaker
    MVN01  Wilkem Edge Villas - Mt View        Daniel & Diana Mugambi

Every other property has been checked against the landlord's balances and is
right; these five carry balances that nobody owes. For each, in one transaction:

  1. ``is_billable`` off and rent 0, so the monthly run, both reminder jobs and
     the monthly statement leave it alone (see ``Tenant.is_billable`` - a zero
     rent alone would still raise a 0.00 row and send a reminder every month);
  2. the books restarted at ``--as-of`` on an opening balance of 0.00, the same
     mechanism ``set_opening_balances`` uses. Nothing is deleted: everything up
     to ``--as-of`` stays on file, counted nowhere, and deleting the opening
     balance (``--undo``) puts the tenancy back on its full history;
  3. rent rows raised for months after ``--as-of`` are deleted (the ledger
     signal posts each reversal). A row with money or credit against it is
     refused, not deleted - that is a payment to look at, not a rent charge.

Other charges, payments and credits dated after ``--as-of`` are listed and kept:
water and other costs are still recoverable on these properties. Any balance
they leave is reported, and the run refuses to apply unless every tenancy
lands on 0.00 (``--allow-nonzero`` keeps it anyway).

Preview is the DEFAULT: the change runs and is rolled back.

Usage (Render Shell):
    python manage.py clear_non_rent_balances
    python manage.py clear_non_rent_balances --apply
    python manage.py clear_non_rent_balances --undo --apply
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

ZERO = Decimal("0.00")

UNITS = ("FMNCH", "FNNCH", "FSCH", "KNCH", "MVN01")
DEFAULT_AS_OF = "2026-10-31"
SOURCE = "Landlord instruction 14 Nov 2026: not charged rent - expenses and other income only"


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Stop rent on the five non-rent properties and bring their balances to nil (preview unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--as-of", default=DEFAULT_AS_OF,
                            help=f"Month end the books restart after (default {DEFAULT_AS_OF}).")
        parser.add_argument("--unit", action="append", default=[],
                            help="Limit to these unit labels (repeatable). Default: all five.")
        parser.add_argument("--allow-nonzero", action="store_true",
                            help="Apply even if a tenancy does not land on 0.00.")
        parser.add_argument("--undo", action="store_true",
                            help="Remove the opening balances this set (rent stays off).")
        parser.add_argument("--apply", action="store_true", help="Keep the change (default: preview).")

    def handle(self, *args, **opts):
        labels = [u.upper() for u in opts["unit"]] or list(UNITS)
        unknown = sorted(set(labels) - set(UNITS))
        if unknown:
            raise CommandError(f"Not a non-rent unit: {', '.join(unknown)}. Expected one of {', '.join(UNITS)}.")

        try:
            as_of = _dt.date.fromisoformat(opts["as_of"])
        except ValueError as exc:
            raise CommandError(f"--as-of {opts['as_of']!r} is not a YYYY-MM-DD date.") from exc
        if (as_of + _dt.timedelta(days=1)).day != 1:
            raise CommandError("--as-of must be the last day of a month.")

        apply = opts["apply"]
        self.stdout.write("APPLY" if apply else "PREVIEW (rolled back)")
        try:
            with transaction.atomic():
                if opts["undo"]:
                    self._undo(labels)
                else:
                    problems = sum(self._clear(label, as_of=as_of, allow_nonzero=opts["allow_nonzero"])
                                   for label in labels)
                    if problems and apply:
                        raise CommandError(f"{problems} problem(s) above; nothing was saved.")
                if not apply:
                    raise _Rollback
        except _Rollback:
            self.stdout.write(self.style.WARNING("Preview rolled back. Re-run with --apply to keep it."))
            return
        self.stdout.write(self.style.SUCCESS("Applied."))

    # -- helpers -----------------------------------------------------------

    def _tenant_for(self, label):
        from apps.tenants.models import CURRENT_STATUSES, Tenant

        tenants = list(Tenant.objects.filter(unit__label__iexact=label, status__in=CURRENT_STATUSES)
                       .select_related("unit__building"))
        if len(tenants) != 1:
            raise CommandError(f"{label}: expected one current tenancy, found {len(tenants)}.")
        return tenants[0]

    def _undo(self, labels):
        from apps.payments.models import OpeningBalance

        for label in labels:
            ob = OpeningBalance.objects.filter(tenant__unit__label__iexact=label, source=SOURCE).first()
            if ob is None:
                self.stdout.write(f"  {label:<6} no opening balance from this command - nothing to undo")
                continue
            self.stdout.write(f"  {label:<6} removing opening {ob.amount:,.2f} at {ob.as_of}")
            ob.delete()

    def _clear(self, label, *, as_of, allow_nonzero) -> int:
        from apps.payments import books
        from apps.payments.models import Arrears, OpeningBalance, Payment, TenantCredit, UtilityCharge
        from apps.payments.monthly_ledger import current_balance

        try:
            tenant = self._tenant_for(label)
        except CommandError as exc:
            self.stdout.write(self.style.ERROR(f"  {exc}"))
            return 1

        problems = 0
        today = _dt.date.today()
        before = current_balance(tenant, today=today)
        self.stdout.write(
            f"\n  {label:<6} {tenant.full_name[:30]:<30} {tenant.unit.building.name}\n"
            f"         rent {tenant.monthly_rent:,.2f} billable={tenant.is_billable} | balance {before:,.2f}"
        )

        # 1. Off the rent roll.
        if tenant.is_billable or tenant.monthly_rent != ZERO:
            tenant.is_billable = False
            tenant.monthly_rent = ZERO
            tenant.save(update_fields=["is_billable", "monthly_rent", "updated_at"])
            self.stdout.write("         rent stopped: billable off, rent 0.00")

        # 2. Books restarted on nil.
        existing = OpeningBalance.objects.filter(tenant=tenant).first()
        if existing is None:
            OpeningBalance.objects.create(tenant=tenant, as_of=as_of, amount=ZERO, source=SOURCE)
            self.stdout.write(f"         books restart after {as_of} at 0.00")
        elif (existing.as_of, existing.amount) != (as_of, ZERO):
            self.stdout.write(f"         opening {existing.amount:,.2f} at {existing.as_of} "
                              f"({existing.source}) -> 0.00 at {as_of}")
            existing.as_of, existing.amount, existing.source = as_of, ZERO, SOURCE
            existing.save()

        # 3. Rent raised for months inside the new books.
        for row in Arrears.objects.filter(books.arrears_q(), tenant=tenant).order_by("period_year", "period_month"):
            money = (row.amount_paid or ZERO) + (row.credit_applied or ZERO)
            period = f"{row.period_month:02d}/{row.period_year}"
            if money > ZERO:
                problems += 1
                self.stdout.write(self.style.ERROR(
                    f"         rent {period} has {money:,.2f} paid/credited against it - not removed; "
                    "check that payment before applying"))
                continue
            self.stdout.write(f"         rent {period} {row.expected_total:,.2f} removed")
            row.delete()

        books.resettle(tenant)

        # What stays inside the books - shown so it can be checked, never touched.
        kept = (
            [f"charge {u.posting_date} {u.label} {u.amount:,.2f}"
             for u in UtilityCharge.objects.filter(books.utilities_q(), tenant=tenant)]
            + [f"payment {p.payment_date} {p.amount:,.2f} {p.reference}"
               for p in Payment.objects.filter(books.payments_q(), tenant=tenant, voided_at__isnull=True)]
            + [f"credit {c.number} {c.credit_date} {c.amount:,.2f} ({c.status})"
               for c in TenantCredit.objects.filter(books.credits_q(), tenant=tenant)]
        )
        for line in kept:
            self.stdout.write(f"         kept: {line}")

        after = current_balance(tenant, today=today)
        if after == ZERO:
            self.stdout.write(self.style.SUCCESS(f"         balance {before:,.2f} -> 0.00"))
        elif allow_nonzero:
            self.stdout.write(self.style.WARNING(
                f"         balance {before:,.2f} -> {after:,.2f} (kept: --allow-nonzero)"))
        else:
            problems += 1
            self.stdout.write(self.style.ERROR(
                f"         balance {before:,.2f} -> {after:,.2f}, not nil - the rows kept above carry it"))
        return problems
