"""
Seed master data for "Wilkem Edge Business Arcade, Matasia".

Reads the property schedule from
  "Wilkem Edge Business Arcade Matasia - Commercial and Residential Units.pdf"
and creates: the building, all 34 units (22 commercial + 12 residential),
and the 12 currently active commercial tenants.

Idempotent — get_or_create on every row, safe to re-run.

Usage (Render Shell):
    python manage.py seed_wilkem_property
"""
import datetime as dt
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

# ---------------------------------------------------------------------------
# Data — verbatim from the property schedule PDF.
# Unit labels have hyphens stripped (G-01 → G01) so the bill ref a tenant
# types is just "90290#G01" with no special characters.
# ---------------------------------------------------------------------------

BUILDING = {
    "name": "Wilkem Edge Business Arcade, Matasia",
    "address": "Matasia",
    "legal_name": "Wilkem Ventures Company Limited",
    "paybill_number": "400222",
    "paybill_account_format": "90290#{unit}",
    "total_floors": 4,
}

# (label, floor, unit_type, classification, rent, statement_descriptor)
COMMERCIAL_UNITS = [
    ("G01", 0, "shop", "BUSINESS", 24000,  "Unit G-01"),
    ("G02", 0, "shop", "BUSINESS", 22500,  "Unit G-02"),
    ("G03", 0, "shop", "BUSINESS", 18000,  "Unit G-03"),
    ("G04", 0, "shop", "BUSINESS", 15000,  "Unit G-04"),
    ("G05", 0, "shop", "BUSINESS", 86500,  "Unit G-05"),
    ("G07", 0, "shop", "BUSINESS", 55000,  "Unit G-07"),
    ("G08", 0, "shop", "BUSINESS", 57800,  "Unit G-08"),
    ("G10", 0, "shop", "BUSINESS", 25000,  "Unit G-10"),
    ("F01", 1, "shop", "BUSINESS", 35000,  "Unit F-01"),
    ("F02", 1, "shop", "BUSINESS", 25000,  "Unit F-02"),
    ("F03", 1, "shop", "BUSINESS", 22500,  "Unit F-03"),
    ("F04", 1, "shop", "BUSINESS", 25000,  "Unit F-04"),
    ("F05", 1, "shop", "BUSINESS", 25000,  "Unit F-05"),
    ("F06", 1, "shop", "BUSINESS", 20000,  "Unit F-06"),
    ("F07", 1, "shop", "BUSINESS", 25000,  "Unit F-07"),
    ("F08", 1, "shop", "BUSINESS", 26000,  "Unit F-08"),
    ("F09", 1, "shop", "BUSINESS", 24000,  "Unit F-09"),
    ("F10", 1, "shop", "BUSINESS", 20000,  "Unit F-10"),
    ("F11", 1, "shop", "BUSINESS", 25000,  "Unit F-11"),
    ("F12", 1, "shop", "BUSINESS", 58760,  "Unit F-12"),
    ("F13A", 1, "shop", "BUSINESS", 24000, "Unit F-13A"),
    ("F13B", 1, "shop", "BUSINESS", 22500, "Unit F-13B"),
]

# (label, floor, unit_type, classification, rent, statement_descriptor)
RESIDENTIAL_UNITS = [
    ("R201", 2, "2br",       "RESIDENTIAL", 25000, "Unit R-201 - 2 Bedroom"),
    ("R202", 2, "1br",       "RESIDENTIAL", 20000, "Unit R-202 - 1 Bedroom"),
    ("R203", 2, "2br",       "RESIDENTIAL", 30000, "Unit R-203 - 2 Bedroom"),
    ("R204", 2, "bedsitter", "RESIDENTIAL", 10000, "Unit R-204 - Studio"),
    ("R301", 3, "2br",       "RESIDENTIAL", 25000, "Unit R-301 - 2 Bedroom"),
    ("R302", 3, "1br",       "RESIDENTIAL", 20000, "Unit R-302 - 1 Bedroom"),
    ("R303", 3, "2br",       "RESIDENTIAL", 30000, "Unit R-303 - 2 Bedroom"),
    ("R304", 3, "bedsitter", "RESIDENTIAL", 10000, "Unit R-304 - Studio"),
    ("R305", 3, "2br",       "RESIDENTIAL", 30000, "Unit R-305 - 2 Bedroom"),
    ("R306", 3, "1br",       "RESIDENTIAL", 20000, "Unit R-306 - 1 Bedroom"),
    ("R307", 3, "1br",       "RESIDENTIAL", 20000, "Unit R-307 - 1 Bedroom"),
    ("R308", 3, "2br",       "RESIDENTIAL", 30000, "Unit R-308 - 2 Bedroom"),
]

# Active commercial tenants
# (unit_label, business_name, suffix, contact_person, phone, kra_pin, rent, deposit, move_in)
TENANTS = [
    ("G01",  "Lecias Enterprises", "Limited",         "Dennis Kerosi",        "0733624892", "P052438828Z", 24000,  75000,  "2026-02-01"),
    ("G02",  "Glow by Ellie",      "Salon",           "Philip Njenga",        "0710602459", "A004392923Z", 22500,  66000,  "2023-03-01"),
    ("G03",  "Glow by Ellie",      "Barber Shop",     "Philip Njenga",        "0710602459", "A004392923Z", 18000,  54000,  "2023-11-01"),
    ("G04",  "Fortify Solutions",  "Limited",         "Hellen Chege",         "0722434022", "P051696399H", 15000,  45000,  "2025-11-01"),
    ("G05",  "Sidai Lonestar",     "Healthcare",      "David Chibeka",        "0722301981", "P052201098W", 86500,  390780, "2023-05-01"),
    ("G07",  "Morton & De Brazza", "Limited",         "Brian Mukolwe",        "0728641184", "P051641930W", 55000,  165000, "2025-10-01"),
    ("G08",  "Mavin House",        "Wares",           "Violet Nafula Juma",   "0715454643", "A005802847Z", 57800,  153000, "2023-02-01"),
    ("G10",  "Shamir Car Wash",    "& Eatery",        "Stephen Kamau",        "0728396204", "A005402165M", 25000,  120000, "2025-08-01"),
    ("F03",  "Elimisha",           "Limited",         "Andrew Mwaura",        "0720772330", "P051243390B", 22500,  67500,  "2026-03-01"),
    ("F12",  "Sidai Lonestar",     "Healthcare Office","David Chibeka",       "0722301981", "P052201098W", 58760,  0,      "2024-06-01"),
    ("F13A", "NKM",                "Advocates",       "Agnes Nyawira Kionga", "0707329013", "A004575535A", 24000,  67500,  "2023-12-01"),
    ("F13B", "GeoTruth",           "Consult",         "Kefa Ouma Ojwando",    "0731440843", "P052294406W", 22500,  67500,  "2025-04-01"),
]


def _normalize_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    return "+" + digits


class Command(BaseCommand):
    help = "Seed Wilkem Edge Business Arcade master data — building, units, active tenants."

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.buildings.models import Building, Unit, UnitStatus
        from apps.tenants.models import Tenant, TenantStatus

        # 1. Building
        building, b_created = Building.objects.get_or_create(
            name=BUILDING["name"],
            defaults={k: v for k, v in BUILDING.items() if k != "name"},
        )
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if b_created else 'Found'} building: {building.name}"
        ))

        # 2. Units
        new_units = 0
        for label, floor, unit_type, classification, rent, descriptor in COMMERCIAL_UNITS + RESIDENTIAL_UNITS:
            unit, created = Unit.objects.get_or_create(
                building=building, label=label,
                defaults={
                    "floor": floor,
                    "unit_type": unit_type,
                    "classification": classification,
                    "monthly_rent": Decimal(str(rent)),
                    "statement_descriptor": descriptor,
                    "status": UnitStatus.VACANT,
                },
            )
            if created:
                new_units += 1
        self.stdout.write(self.style.SUCCESS(
            f"Units created: {new_units} (total in seed: {len(COMMERCIAL_UNITS) + len(RESIDENTIAL_UNITS)})."
        ))

        # 3. Active tenants
        new_tenants = 0
        for (unit_label, name, suffix, contact, phone, kra_pin,
             rent, deposit, move_in) in TENANTS:
            try:
                unit = Unit.objects.get(building=building, label=unit_label)
            except Unit.DoesNotExist:
                self.stdout.write(self.style.ERROR(
                    f"  Unit {unit_label} not found — skipping tenant {name}"
                ))
                continue
            # Synthetic ID for business tenants — they don't have national IDs.
            # `id_number` is unique, so we suffix with the unit label.
            id_number = f"BIZ-{unit_label}"
            tenant, created = Tenant.objects.get_or_create(
                id_number=id_number,
                defaults={
                    "first_name": name,
                    "last_name": suffix,
                    "care_of": f"c/o {contact}" if contact else "",
                    "phone": _normalize_phone(phone),
                    "kra_pin": kra_pin,
                    "unit": unit,
                    "monthly_rent": Decimal(str(rent)),
                    "deposit_paid": Decimal(str(deposit)),
                    "move_in_date": dt.date.fromisoformat(move_in),
                    "status": TenantStatus.ACTIVE,
                },
            )
            if created:
                new_tenants += 1
                if unit.status == UnitStatus.VACANT:
                    unit.status = UnitStatus.OCCUPIED_UNPAID
                    unit.save(update_fields=["status"])
        self.stdout.write(self.style.SUCCESS(
            f"Tenants created: {new_tenants} (total in seed: {len(TENANTS)})."
        ))
        self.stdout.write(self.style.SUCCESS(
            "Wilkem Edge Business Arcade master data seeded."
        ))
