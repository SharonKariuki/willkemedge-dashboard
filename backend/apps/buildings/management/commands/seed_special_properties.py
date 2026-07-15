"""
Seed the non-rental properties: the three farms and the Baobab Karen residence.

These have no tenants — farms record manual income + expenses, and Baobab Karen
records expenses only (income is disabled). They are kept out of the rent-roll
importer because they carry no units, so this command creates them directly.

Codes follow Dr. Osoro's official property coding (2026-06-16):
    FS  Wilkem Navillus Farm, Soy Eldoret          (farm)
    FMN Wilkem Farm, Mwongori Nyamira              (farm)
    FNN Wilkem Farm, Nyariacho Nyamira             (farm)
    KN  Wilkem Residence, The Baobab Karen         (expenses only)

Idempotent: re-running updates the same buildings in place (matched on code).

    python manage.py seed_special_properties
    python manage.py seed_special_properties --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.buildings.models import Building, PropertyType

# (code, name, property_type)
SPECIAL_PROPERTIES = [
    ("FS",  "Wilkem Navillus Farm, Soy Eldoret",   PropertyType.FARM),
    ("FMN", "Wilkem Farm, Mwongori Nyamira",       PropertyType.FARM),
    ("FNN", "Wilkem Farm, Nyariacho Nyamira",      PropertyType.FARM),
    ("KN",  "Wilkem Residence, The Baobab Karen",  PropertyType.EXPENSE_ONLY),
]


class Command(BaseCommand):
    help = "Create the farm + Baobab Karen properties (no tenants) with the right property_type."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change, then roll back.")

    def handle(self, *args, **opts):
        created = updated = unchanged = 0

        with transaction.atomic():
            for code, name, ptype in SPECIAL_PROPERTIES:
                existing = Building.objects.filter(code=code).first()
                if existing is None:
                    Building.objects.create(code=code, name=name, property_type=ptype)
                    created += 1
                    self.stdout.write(f"  + {code} {name} [{ptype}]")
                elif existing.name != name or existing.property_type != ptype:
                    existing.name = name
                    existing.property_type = ptype
                    existing.save(update_fields=["name", "property_type"])
                    updated += 1
                    self.stdout.write(f"  ~ {code} {name} [{ptype}]")
                else:
                    unchanged += 1

            if opts["dry_run"]:
                transaction.set_rollback(True)

        summary = f"\n{created} created, {updated} updated, {unchanged} unchanged."
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING(summary + "  [DRY RUN — rolled back]"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
            self.stdout.write(
                "Farms accept manual income + expenses; Baobab Karen (KN) is expenses-only."
            )
