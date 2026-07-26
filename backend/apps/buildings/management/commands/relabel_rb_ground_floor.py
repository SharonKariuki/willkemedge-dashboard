"""
Relabel the Road Block (RB) ground-floor units so the label encodes the floor.

The RB coding scheme uses the middle digit as the floor number:

    RB0 01..09   ground floor (floor 0)
    RB1 01..11   floor 1
    RB2 01..11   floor 2   ... etc.

The upper floors already carry their floor digit (RB101, RB201, …), but the
ground floor was loaded as two-digit labels (RB01..RB09) with no floor digit.
This command inserts the missing '0' so the ground floor reads RB001..RB009,
consistent with the rest of the building.

It is safe to run against production:

  * Old labels are preserved as `UnitAlias` rows, so any M-Pesa/bank payment
    that still quotes the OLD reference (e.g. '90290#RB01') keeps auto-matching
    through the transition — the matcher tries the current label first, then
    falls back to aliases. See apps/payments/matching.match_tenant.
  * Idempotent: units already in RB0dd form are skipped, so re-running is a
    no-op.
  * DRY-RUN by default. Nothing is written unless you pass --apply.

Usage:
    python manage.py relabel_rb_ground_floor            # preview only
    python manage.py relabel_rb_ground_floor --apply    # perform the relabel
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Matches an RB ground-floor label: 'RB' + exactly two digits (RB01..RB99).
# Upper floors are three digits (RB101, RB201, …) and never match this.
GROUND_FLOOR_RE = re.compile(r"^RB(\d{2})$")


class Command(BaseCommand):
    help = (
        "Relabel RB ground-floor units RB01..RB09 -> RB001..RB009 (floor-encoded), "
        "keeping the old label as a payment-matching alias. Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually perform the relabel. Without this flag the command "
                 "only previews the changes and writes nothing.",
        )
        parser.add_argument(
            "--building-code",
            default="RB",
            help="Building code to target (default: RB).",
        )

    def handle(self, *args, **options):
        from apps.buildings.models import Building, Unit, UnitAlias

        apply = options["apply"]
        code = options["building_code"]

        try:
            building = Building.objects.get(code=code)
        except Building.DoesNotExist as err:
            raise CommandError(
                f"No building with code {code!r}. Nothing to do."
            ) from err
        except Building.MultipleObjectsReturned as err:
            raise CommandError(
                f"Multiple buildings share code {code!r}; codes must be unique."
            ) from err

        # Build the rename plan and check for target collisions up front.
        plan = []          # (unit, old_label, new_label)
        skipped_existing = []
        for unit in building.units.order_by("label"):
            m = GROUND_FLOOR_RE.match(unit.label)
            if not m:
                continue  # already floor-encoded (RB0dd / RB1dd / …) or non-RB
            new_label = f"RB0{m.group(1)}"
            plan.append((unit, unit.label, new_label))

        if not plan:
            self.stdout.write(self.style.SUCCESS(
                f"Nothing to relabel — no two-digit RB ground-floor labels found "
                f"in {building.name}. (Already floor-encoded?)"
            ))
            return

        # Guard: a target label must not already be taken by another unit
        # anywhere (the global Upper(label) unique constraint would reject it,
        # and it would signal a data problem worth stopping on).
        for unit, old_label, new_label in plan:
            clash = (
                Unit.objects.filter(label__iexact=new_label)
                .exclude(pk=unit.pk)
                .select_related("building")
                .first()
            )
            if clash:
                raise CommandError(
                    f"Cannot rename {old_label!r} -> {new_label!r}: label "
                    f"{new_label!r} is already used by unit #{clash.pk} in "
                    f"'{clash.building.name}'. Resolve the collision first."
                )

        # Preview.
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{building.name} ({building.code}) — ground-floor relabel plan:"
        ))
        for _unit, old_label, new_label in plan:
            self.stdout.write(f"  {old_label:>6}  ->  {new_label:<6}  (alias kept: {old_label})")
        if skipped_existing:
            self.stdout.write(f"\n  Skipped (already floor-encoded): {len(skipped_existing)}")

        if not apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {len(plan)} unit(s) would be relabelled. "
                f"Re-run with --apply to write."
            ))
            return

        with transaction.atomic():
            for unit, old_label, new_label in plan:
                # Rename the unit first, then register the old label as an alias.
                # Order matters: UnitAlias.clean() refuses an alias that collides
                # with a CURRENT unit label, so the old label must be free first.
                if unit.statement_descriptor:
                    unit.statement_descriptor = unit.statement_descriptor.replace(
                        old_label, new_label
                    )
                unit.label = new_label
                unit.full_clean()
                unit.save(update_fields=["label", "statement_descriptor", "updated_at"])

                alias, created = UnitAlias.objects.get_or_create(
                    unit=unit,
                    label=old_label,
                    defaults={"note": "Retired ground-floor label (floor-code relabel)"},
                )
                if created:
                    alias.full_clean()

        self.stdout.write(self.style.SUCCESS(
            f"\nRelabelled {len(plan)} ground-floor unit(s) in {building.name}. "
            f"Old labels kept as aliases so existing payment references still match."
        ))
