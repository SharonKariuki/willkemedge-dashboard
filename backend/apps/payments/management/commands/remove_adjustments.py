"""
Take out hand-entered balancing charges and credits, by id.

Between 24 and 27 October 2026 balances were brought to the landlord's sheet
with "Billing after system reconciliation" charges and "Credit after
reconciliation" account credits. Where the books are now restarted at 31 Aug
(``set_opening_balances``), those entries count the same gap a second time,
and they sit on the wrong accounts (4150 recovered income, 3300). The app
can void a credit but has no way to remove a charge; this does both:

  * a charge (``--charge <id>``) is deleted — the ledger signal posts its
    reversal. A charge a credit note has been issued against is refused.
  * a credit (``--credit <number>``) is voided through ``void_credit``: rent it
    settled is re-opened and a mirror-image journal is posted.

Ids and numbers are listed in the preview with unit, description and amount,
so check them against the screen before ``--apply``.

Preview is the DEFAULT: the change runs and is rolled back.

Usage (Render Shell):
    python manage.py remove_adjustments --charge 62 --charge 63 --credit CR-00009 \\
        --reason "Replaced by the 31 Aug opening balance"
    python manage.py remove_adjustments ... --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Delete hand-entered charges and void credits, by id (preview unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--charge", action="append", type=int, default=[], help="UtilityCharge id")
        parser.add_argument("--credit", action="append", default=[], help="Credit number, e.g. CR-00009")
        parser.add_argument("--reason", required=True, help="Recorded on each voided credit and in the audit log")
        parser.add_argument("--apply", action="store_true", help="Keep the change (default: preview)")

    def handle(self, *args, charge, credit, reason, apply, **options):
        from apps.payments.models import TenantCredit, UtilityCharge

        if not charge and not credit:
            raise CommandError("Name at least one --charge or --credit.")
        reason = reason.strip()
        if not reason:
            raise CommandError("--reason cannot be blank.")

        charges = {c.pk: c for c in UtilityCharge.objects.select_related("tenant__unit").filter(pk__in=charge)}
        credits = {c.number: c for c in TenantCredit.objects.select_related("tenant__unit").filter(number__in=credit)}
        missing = [str(pk) for pk in charge if pk not in charges] + [n for n in credit if n not in credits]
        if missing:
            raise CommandError(f"Not found: {', '.join(missing)}. Nothing was written.")

        self.stdout.write("APPLY" if apply else "PREVIEW (rolled back)")
        try:
            with transaction.atomic():
                for pk in charge:
                    self._remove_charge(charges[pk], reason)
                for number in credit:
                    self._void_credit(credits[number], reason)
                if not apply:
                    raise _Rollback
        except _Rollback:
            self.stdout.write("Preview only — nothing was kept. Run again with --apply.")

    def _remove_charge(self, charge, reason):
        from apps.accounts import audit
        from apps.payments.models import CreditStatus

        line = (
            f"charge {charge.pk} {charge.tenant.unit.label} {charge.tenant} — "
            f"{charge.label!r} {charge.amount:,.2f} ({charge.period_month}/{charge.period_year})"
        )
        if charge.credit_notes.filter(status=CreditStatus.ISSUED).exists():
            raise CommandError(f"{line}: a credit note is issued against it — void that first. Nothing was written.")
        self.stdout.write(f"  delete {line}")
        audit.record(
            action="utility_charge.delete",
            object_type="tenant",
            object_id=charge.tenant_id,
            object_label=str(charge.tenant),
            summary=f"Removed charge {charge.label!r} {charge.amount} — {reason}",
            old_values={"id": charge.pk, "label": charge.label, "amount": str(charge.amount),
                        "period": f"{charge.period_month}/{charge.period_year}"},
        )
        charge.delete()

    def _void_credit(self, credit, reason):
        from apps.payments import credits

        line = (
            f"credit {credit.number} {credit.tenant.unit.label} {credit.tenant} — "
            f"{credit.description!r} {credit.amount:,.2f}"
        )
        if credit.is_void:
            self.stdout.write(f"  skip {line}: already void")
            return
        self.stdout.write(f"  void {line}")
        try:
            credits.void_credit(credit, reason=reason)
        except credits.CreditError as exc:
            raise CommandError(f"{line}: {exc} Nothing was written.") from None
