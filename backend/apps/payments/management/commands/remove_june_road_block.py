"""
Remove June 2026 from Wilkem Edge Apartments - Road Block, Eldoret.

June is not an ordinary billed month on this property: it is the opening
cutover, the month the building was loaded into the system. It carries the
"Arrears B/F July-2026" position the landlord's 21 Aug 2026 statement starts
from, and the ledger side of that cutover.

Removing it therefore removes real records, and the landlord has asked for
exactly that. What goes:

  * every June 2026 Arrears row for a Road Block tenant — including the four
    that still carry a balance (Erick Odhiambo, Kevin Awino, Wilberforce
    Mwanga, Beatrice Okumu Adhiambo, all moved out and all off the 21 Aug
    statement), and the rows whose pre-July balance the reconciliation waived
    into the July B/F;
  * every June 2026 journal entry for the building, and its lines — the
    opening security-deposit liabilities, the opening arrears, and the one
    opening credit.

What is deliberately LEFT ALONE:

  * Payments whose period is June. Those are cash the tenant actually paid;
    deleting them would erase money received, which is not what removing a
    billing month means. Any that exist are reported instead so they can be
    re-pointed by hand if the landlord wants them moved to July.
  * July and August, and every other property.

Deposits are the material loss here: the 53 "Opening security deposit held"
entries are what the business owes each tenant back at move-out, and after
this command that liability is no longer on the books. This is called out in
the run so it cannot be deleted by accident.

DRY-RUN BY DEFAULT. Nothing is deleted without --apply.

Usage:
    python manage.py remove_june_road_block
    python manage.py remove_june_road_block --apply
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

BUILDING_MATCH = "Road Block"
PERIOD = (2026, 6)


class Command(BaseCommand):
    help = (
        "Delete June 2026 arrears and journal entries for Road Block Eldoret "
        "(the opening cutover month). Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Actually delete. Without this the command only reports.",
        )

    def handle(self, *args, **options):
        from apps.buildings.models import Building
        from apps.ledger.models import JournalEntry
        from apps.payments.models import Arrears, Payment
        from apps.tenants.models import Tenant

        self.apply = options["apply"]
        year, month = PERIOD

        building = Building.objects.filter(name__icontains=BUILDING_MATCH).first()
        if building is None:
            raise CommandError(f"No building matching {BUILDING_MATCH!r}")

        tenants = Tenant.objects.filter(unit__building=building)
        arrears = Arrears.objects.filter(
            tenant__in=tenants, period_year=year, period_month=month
        )
        entries = JournalEntry.objects.filter(
            building=building, period_year=year, period_month=month
        )
        payments = Payment.objects.filter(
            tenant__in=tenants, period_year=year, period_month=month,
            voided_at__isnull=True,
        )

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{building.name} — June {year}"
        ))

        outstanding = arrears.filter(is_cleared=False)
        self.stdout.write(
            f"  arrears rows          : {arrears.count()} "
            f"(charged {arrears.aggregate(x=Sum('expected_rent'))['x'] or 0}, "
            f"waived {arrears.aggregate(x=Sum('waived_amount'))['x'] or 0})"
        )
        self.stdout.write(self.style.WARNING(
            f"  ...still owing        : {outstanding.count()} rows, "
            f"{outstanding.aggregate(x=Sum('balance'))['x'] or 0} written off by this delete"
        ))
        for a in outstanding.select_related("tenant", "tenant__unit"):
            self.stdout.write(
                f"      {a.tenant.unit.label:<7} {a.tenant.full_name:<28} "
                f"{a.balance} ({a.tenant.status})"
            )

        self.stdout.write(f"  journal entries       : {entries.count()}")
        for memo, n in self._by_memo(entries):
            self.stdout.write(f"      {n:>3}  {memo}")
        deposits = [n for memo, n in self._by_memo(entries) if "deposit" in memo.lower()]
        if deposits:
            self.stdout.write(self.style.WARNING(
                f"      ^ {sum(deposits)} of these are tenant deposit liabilities — "
                "what the business owes back at move-out"
            ))

        if payments.exists():
            self.stdout.write(self.style.WARNING(
                f"  June-period payments  : {payments.count()} "
                f"({payments.aggregate(x=Sum('amount'))['x']}) — KEPT, not deleted"
            ))
            for p in payments.select_related("tenant", "tenant__unit")[:20]:
                self.stdout.write(
                    f"      {p.tenant.unit.label:<7} {p.tenant.full_name:<28} "
                    f"{p.amount}  {p.payment_date}  {p.reference}"
                )
            self.stdout.write(
                "      (their period still reads 6/2026; re-point by hand if they "
                "should sit in July)"
            )
        else:
            self.stdout.write("  June-period payments  : none")

        n_arrears, n_entries = arrears.count(), entries.count()
        if not (n_arrears or n_entries):
            self.stdout.write(self.style.SUCCESS("\nNothing to remove — June is already gone."))
            return

        if not self.apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — would delete {n_arrears} arrears row(s) and "
                f"{n_entries} journal entr(ies). Re-run with --apply."
            ))
            return

        with transaction.atomic():
            entries.delete()   # cascades to JournalLine
            arrears.delete()
        self.stdout.write(self.style.SUCCESS(
            f"\nDeleted {n_arrears} arrears row(s) and {n_entries} journal entr(ies) "
            f"for June {year}."
        ))

    @staticmethod
    def _by_memo(entries):
        from collections import Counter

        counter = Counter()
        for entry in entries:
            memo = entry.memo.split("—")[0].strip() if "—" in entry.memo else entry.memo[:40]
            counter[memo] += 1
        return counter.most_common()
