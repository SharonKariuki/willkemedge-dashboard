"""
Audit — and optionally repair — the water meter chains behind every water charge.

A meter's history is a chain: each month opens exactly where the previous month
closed. Three things have historically broken that chain, and all three are
still sitting in the data:

  * the staff form pre-filled "previous reading" from the newest charge on file
    regardless of period, so any backfilled month opened on a later month's
    closing figure;
  * correcting a reading revised that one month and left every month after it
    opening on a dial position that no longer existed;
  * the spreadsheet importer carried Excel's own UNITS CONSUMED and VALUE
    figures, which need not agree with the readings in the row above them.

Each break bills a tenant for water nobody metered, in one direction or the
other. This command finds them and, with ``--apply``, re-derives the affected
months from the readings.

Usage:
    python manage.py audit_water_readings
    python manage.py audit_water_readings --building DON
    python manage.py audit_water_readings --unit DON1A --apply
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.payments.meter_service import WATER_LABEL, meter_history, recompute_chain_after

# `recompute_chain_after` skips everything at or before this period, so a
# period no charge can occupy means "rebuild the whole chain".
BEGINNING = (0, 0)


def _fmt(value):
    if value is None:
        return "—"
    return f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, Decimal) else str(value)


def audit_chain(tenant, *, label=WATER_LABEL):
    """Return the problems on one meter's chain, oldest first.

    Read-only: it reports, it never writes. The repair is `recompute_chain_after`.
    """
    problems = []
    prior = None  # (period, closing_reading) of the last month with a dial figure

    for charge in meter_history(tenant, label=label):
        period = f"{charge.period_month:02d}/{charge.period_year}"
        opening, closing = charge.opening_reading, charge.closing_reading

        if closing is None:
            problems.append((period, "no closing reading — the chain cannot continue past it"))
            prior = None
            continue

        if prior is not None and opening != prior[1]:
            problems.append((
                period,
                f"opens at {_fmt(opening)} but {prior[0]} closed at {_fmt(prior[1])}"
                f" — {_fmt(abs((opening or Decimal('0')) - prior[1]))} units unaccounted for",
            ))
        elif opening is None:
            problems.append((period, "no opening reading — consumption is not derivable"))

        if opening is not None and closing < opening:
            problems.append((
                period, f"closes at {_fmt(closing)} below its opening {_fmt(opening)}"
                        " — meter swap, rollover, or a transposed figure",
            ))
        elif opening is not None and charge.units != closing - opening:
            problems.append((
                period,
                f"billed {_fmt(charge.units)} units but the readings give "
                f"{_fmt(closing - opening)}",
            ))

        if charge.units and charge.rate_per_unit() is None:
            problems.append((
                period,
                f"amount {_fmt(charge.amount)} is not a whole rate × {_fmt(charge.units)} units",
            ))

        prior = (period, closing)

    return problems


class Command(BaseCommand):
    help = "Report (and with --apply, repair) discontinuous or mis-derived water meter chains."

    def add_arguments(self, parser):
        parser.add_argument("--building", help="Limit to one building code or name.")
        parser.add_argument("--unit", help="Limit to one unit label.")
        parser.add_argument("--label", default=WATER_LABEL, help=f"Charge label (default: {WATER_LABEL!r}).")
        parser.add_argument(
            "--apply", action="store_true",
            help="Re-derive the affected months from the readings. Without it, report only.",
        )

    def handle(self, *args, **opts):
        from apps.buildings.models import Unit

        label = opts["label"]
        units = Unit.objects.select_related("building").order_by("building__code", "label")
        if opts["building"]:
            b = opts["building"]
            units = units.filter(Q(building__code__iexact=b) | Q(building__name__icontains=b))
        if opts["unit"]:
            units = units.filter(label__iexact=opts["unit"])

        checked = flagged = repaired = 0
        with transaction.atomic():
            for unit in units:
                # One tenant is enough to reach the meter: the history is scoped
                # to the unit, so any current or former occupant sees all of it.
                tenant = unit.tenants.order_by("-move_in_date", "-id").first()
                if tenant is None or not meter_history(tenant, label=label).exists():
                    continue
                checked += 1

                problems = audit_chain(tenant, label=label)
                if not problems:
                    continue
                flagged += 1
                self.stdout.write(self.style.WARNING(f"\n{unit.building.code} {unit.label}"))
                for period, problem in problems:
                    self.stdout.write(f"  {period}  {problem}")

                if opts["apply"]:
                    changed = recompute_chain_after(tenant, after_period=BEGINNING, label=label)
                    repaired += len(changed)
                    for charge in changed:
                        self.stdout.write(self.style.SUCCESS(
                            f"  -> {charge.period_month:02d}/{charge.period_year} re-derived: "
                            f"{_fmt(charge.opening_reading)} -> {_fmt(charge.closing_reading)} = "
                            f"{_fmt(charge.units)} units, KES {_fmt(charge.amount)}"
                        ))

            if not opts["apply"]:
                transaction.set_rollback(True)

        summary = f"\n{checked} meter(s) checked, {flagged} with problems"
        if opts["apply"]:
            self.stdout.write(self.style.SUCCESS(f"{summary}, {repaired} charge(s) re-derived."))
        else:
            self.stdout.write(self.style.WARNING(
                f"{summary}. Re-run with --apply to re-derive them from the readings."
            ))
