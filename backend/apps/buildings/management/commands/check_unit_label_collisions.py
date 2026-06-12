"""
Detect any Unit labels that are shared across buildings.

The matcher tries to map a bill ref like '90290#G01' to a single Unit by
label. If two buildings ever share a label, the system can no longer
safely auto-assign — it has no way to know which G01 the tenant means.

`apps.payments.matching.match_tenant` already refuses to silently guess
when a label is ambiguous (returns None → event lands in UNMATCHED), but
that means real money sits manual until labels are disambiguated.

Run this BEFORE adding a new property to confirm no incoming labels
collide with the existing portfolio:

    python manage.py check_unit_label_collisions
"""
from collections import defaultdict

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Report any Unit labels that collide across buildings."

    def handle(self, *args, **options):
        from apps.buildings.models import Unit

        # Group case-insensitively — match_tenant does iexact, so 'g01' and 'G01' collide too.
        by_label = defaultdict(list)
        for u in Unit.objects.select_related("building").only("label", "building__name"):
            by_label[u.label.upper()].append((u.building.name, u.label))

        collisions = {k: v for k, v in by_label.items() if len(v) > 1}
        total_units = sum(len(v) for v in by_label.values())

        if not collisions:
            self.stdout.write(self.style.SUCCESS(
                f"OK — no label collisions across {total_units} units in "
                f"{len({b for v in by_label.values() for b, _ in v})} buildings."
            ))
            return

        self.stdout.write(self.style.ERROR(
            f"FOUND {len(collisions)} colliding label(s) across buildings:\n"
        ))
        for upper_label, occurrences in sorted(collisions.items()):
            self.stdout.write(f"  '{upper_label}' appears in:")
            for building_name, exact_label in occurrences:
                self.stdout.write(f"     - {building_name!s} (as '{exact_label}')")
            self.stdout.write("")

        self.stdout.write(self.style.WARNING(
            "Bill refs matching any of these labels CANNOT auto-assign. "
            "Rename one side (e.g. add a building prefix like 'MAT-G01') "
            "and re-run."
        ))
