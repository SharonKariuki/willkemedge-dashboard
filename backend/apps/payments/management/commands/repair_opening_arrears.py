"""
Rebuild opening-balance arrears rows that a payment silently restated.

Background
----------
The cutover import writes one Arrears row per tenant carrying the balance
brought forward from the old books — ``expected_rent`` holds the *opening
balance*, not a month's rent — and posts the matching journal entry
(``source_type='opening_ar'``: DR 1040 / CR opening equity).

``_update_arrears`` then recomputed ``expected_rent`` from
``tenant.monthly_rent`` on every payment. The first time a tenant paid into
their cutover period, the brought-forward figure was overwritten with a month's
rent — in both directions. A KES 1,000 opening arrear became KES 7,000 of debt
the tenant never owed; a KES 74,700 one collapsed to KES 8,300, writing off
KES 66,400 that was genuinely outstanding.

The ledger was never touched, so the opening journal entries still hold the
correct figures. This command replays them back onto the arrears rows.

``services._update_arrears`` no longer rewrites the obligation, so a repaired
row stays repaired.

Safety
------
Preview is the DEFAULT. Nothing is written without ``--apply``.

Usage (Render Shell):
    python manage.py repair_opening_arrears              # preview the diff
    python manage.py repair_opening_arrears --apply      # commit it
    python manage.py repair_opening_arrears --tenant 110 # scope to one tenant
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction

ZERO = Decimal("0.00")

#: The receivables account the opening arrears entry debits.
AR_CODE = "1040"


class Command(BaseCommand):
    help = "Restore opening-balance arrears rows from their ledger journal entries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the repairs. Without this the command only previews them.",
        )
        parser.add_argument(
            "--tenant", type=int, default=None,
            help="Restrict to a single tenant id.",
        )

    def handle(self, *args, **opts):
        from apps.ledger.models import JournalEntry
        from apps.payments.models import Arrears

        entries = JournalEntry.objects.filter(source_type="opening_ar").prefetch_related(
            "lines__account"
        )
        if opts["tenant"]:
            entries = entries.filter(source_id=opts["tenant"])

        repairs, clean, orphans = [], 0, []

        for entry in entries:
            opening = sum(
                (line.debit - line.credit)
                for line in entry.lines.all()
                if line.account.code == AR_CODE
            ) or ZERO
            # A net credit means the tenant was ahead at cutover; the row is
            # raised at a zero obligation, exactly as the importer wrote it.
            target_rent = max(opening, ZERO)

            row = Arrears.objects.filter(
                tenant_id=entry.source_id,
                period_month=entry.date.month,
                period_year=entry.date.year,
            ).select_related("tenant", "tenant__unit").first()

            if row is None:
                orphans.append((entry.source_id, entry.date, target_rent))
                continue

            if row.expected_rent == target_rent:
                clean += 1
                continue

            repairs.append((row, target_rent))

        self._report(repairs, clean, orphans)

        if not repairs:
            return

        if not opts["apply"]:
            self.stdout.write(self.style.WARNING(
                "\nPreview only — nothing written. Re-run with --apply to commit."
            ))
            return

        from apps.payments.services import apply_available_credit

        with db_transaction.atomic():
            for row, target_rent in repairs:
                row.expected_rent = target_rent
                # The opening row is a brought-forward balance, never a VAT-able
                # month's rent, so it carries no VAT of its own.
                row.expected_vat = ZERO
                covered = row.amount_paid + row.waived_amount + row.credit_applied
                row.balance = max(target_rent - covered, ZERO)
                row.is_cleared = covered >= target_rent
                row.save(update_fields=[
                    "expected_rent", "expected_vat", "balance", "is_cleared", "updated_at",
                ])

            # Cutting an inflated opening balance back down turns what the
            # tenant already paid into surplus. Credit is normally drawn against
            # a period only as it is raised, and these periods were raised long
            # ago — so sweep it forward by hand, oldest open period first, or the
            # money would sit banked while the tenant still reads as owing.
            swept = ZERO
            for tenant in {row.tenant for row, _ in repairs}:
                for period in Arrears.objects.filter(
                    tenant=tenant, is_cleared=False
                ).order_by("period_year", "period_month"):
                    before = period.credit_applied
                    apply_available_credit(period)
                    swept += period.credit_applied - before

        self.stdout.write(self.style.SUCCESS(f"\nRepaired {len(repairs)} arrears row(s)."))
        if swept:
            self.stdout.write(self.style.SUCCESS(
                f"Swept {swept:,.2f} of released credit onto open periods."
            ))

    # ── reporting ────────────────────────────────────────────────────────────

    def _report(self, repairs, clean, orphans):
        if not repairs:
            self.stdout.write(self.style.SUCCESS(
                f"Nothing to repair — {clean} opening row(s) already match the ledger."
            ))
        else:
            self.stdout.write(
                f"\n{'TENANT':<28} {'UNIT':<8} {'BOOKED':>11} {'LEDGER':>11} "
                f"{'PAID':>11} {'BAL NOW':>11} {'BAL AFTER':>11}"
            )
            self.stdout.write("-" * 96)
            overstated = understated = ZERO
            for row, target_rent in sorted(repairs, key=lambda r: r[1] - r[0].expected_rent):
                covered = row.amount_paid + row.waived_amount + row.credit_applied
                after = max(target_rent - covered, ZERO)
                drift = row.expected_rent - target_rent
                if drift > 0:
                    overstated += drift
                else:
                    understated += -drift
                unit = getattr(row.tenant.unit, "label", "—")
                self.stdout.write(
                    f"{str(row.tenant)[:28]:<28} {unit:<8} "
                    f"{row.expected_rent:>11,.2f} {target_rent:>11,.2f} "
                    f"{row.amount_paid:>11,.2f} {row.balance:>11,.2f} {after:>11,.2f}"
                )
            self.stdout.write("-" * 96)
            self.stdout.write(
                f"{len(repairs)} row(s) to repair · "
                f"arrears overstated by {overstated:,.2f} · "
                f"understated by {understated:,.2f} · "
                f"net {understated - overstated:+,.2f} owed to the book"
            )
            self.stdout.write(f"{clean} row(s) already correct.")
            self._report_released_credit(repairs)

        self._report_orphans(orphans)

    def _report_released_credit(self, repairs):
        """Payments beyond a restored (smaller) opening balance become credit."""
        released = []
        for row, target_rent in repairs:
            covered = row.amount_paid + row.waived_amount + row.credit_applied
            surplus = covered - target_rent
            if surplus > 0:
                released.append((row.tenant, surplus))
        if not released:
            return
        total = sum(s for _, s in released)
        self.stdout.write(
            f"\n{len(released)} tenant(s) release {total:,.2f} of credit, applied to their "
            f"oldest open periods on --apply:"
        )
        for tenant, surplus in sorted(released, key=lambda r: -r[1]):
            self.stdout.write(f"  {str(tenant)[:40]:<40} {surplus:>11,.2f}")

    def _report_orphans(self, orphans):
        """An opening entry whose arrears row was deleted — a human decision."""
        if not orphans:
            return
        self.stdout.write(self.style.WARNING(
            f"\n{len(orphans)} opening entr(ies) have no arrears row — review by hand:"
        ))
        for tenant_id, date, opening in orphans:
            self.stdout.write(f"  tenant {tenant_id}  {date}  opening {opening:,.2f}")
