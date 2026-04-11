"""
Seed the database with sample buildings and units for local dev.

Usage:
    python manage.py seed_dev_data
    python manage.py seed_dev_data --flush   # delete existing first
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.buildings.models import Building, Unit, UnitStatus

BUILDINGS = [
    {
        "name": "Willkemedge Apartments",
        "address": "Moi Avenue, Nairobi",
        "total_floors": 5,
        "units": [
            ("A1", 1, "single", 8000),
            ("A2", 1, "single", 8000),
            ("A3", 1, "double", 12000),
            ("B1", 2, "bedsitter", 15000),
            ("B2", 2, "bedsitter", 15000),
            ("B3", 2, "1br", 20000),
            ("C1", 3, "1br", 20000),
            ("C2", 3, "2br", 30000),
            ("C3", 3, "2br", 30000),
            ("D1", 4, "3br", 45000),
        ],
    },
    {
        "name": "Osoro Heights",
        "address": "Kenyatta Road, Kiambu",
        "total_floors": 3,
        "units": [
            ("101", 1, "single", 7000),
            ("102", 1, "single", 7000),
            ("103", 1, "double", 10000),
            ("201", 2, "1br", 18000),
            ("202", 2, "1br", 18000),
            ("301", 3, "2br", 28000),
        ],
    },
    {
        "name": "Willkemedge Commercial",
        "address": "Tom Mboya St, Nairobi",
        "total_floors": 1,
        "units": [
            ("Shop 1", 0, "shop", 35000),
            ("Shop 2", 0, "shop", 35000),
            ("Shop 3", 0, "shop", 40000),
        ],
    },
]

# Assign some units a non-vacant status for visual variety in dev.
STATUS_OVERRIDES = {
    "Willkemedge Apartments": {
        "A1": UnitStatus.OCCUPIED_PAID,
        "A2": UnitStatus.OCCUPIED_PARTIAL,
        "B1": UnitStatus.OCCUPIED_UNPAID,
        "C2": UnitStatus.ARREARS,
        "D1": UnitStatus.OCCUPIED_PAID,
    },
    "Osoro Heights": {
        "101": UnitStatus.OCCUPIED_PAID,
        "201": UnitStatus.OCCUPIED_PARTIAL,
    },
    "Willkemedge Commercial": {
        "Shop 1": UnitStatus.OCCUPIED_PAID,
        "Shop 3": UnitStatus.ARREARS,
    },
}


class Command(BaseCommand):
    help = "Seed buildings and units for local development."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all buildings and units before seeding.",
        )

    def handle(self, *args, **options):
        if options["flush"]:
            Unit.objects.all().delete()
            Building.objects.all().delete()
            self.stdout.write(self.style.WARNING("Flushed existing data."))

        for bdata in BUILDINGS:
            building, created = Building.objects.get_or_create(
                name=bdata["name"],
                defaults={
                    "address": bdata["address"],
                    "total_floors": bdata["total_floors"],
                },
            )
            verb = "Created" if created else "Exists"
            self.stdout.write(f"  {verb} building: {building.name}")

            overrides = STATUS_OVERRIDES.get(bdata["name"], {})

            for label, floor, unit_type, rent in bdata["units"]:
                unit, ucreated = Unit.objects.get_or_create(
                    building=building,
                    label=label,
                    defaults={
                        "floor": floor,
                        "unit_type": unit_type,
                        "monthly_rent": Decimal(rent),
                        "status": overrides.get(label, UnitStatus.VACANT),
                    },
                )
                if ucreated:
                    self.stdout.write(f"    + Unit {label} ({unit.get_status_display()})")

        total = Unit.objects.count()
        self.stdout.write(
            self.style.SUCCESS(f"\nSeeded {total} units across {Building.objects.count()} buildings.")
        )
