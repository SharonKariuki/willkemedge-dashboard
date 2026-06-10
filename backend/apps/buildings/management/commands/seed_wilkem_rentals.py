"""
Seed the three rental properties from "Wilkem Properties & Tenants - 8-06-2026.pdf":

    1. Wilkem Edge Apartments — Seniors Estate, Eldoret    (~50 units)
    2. Wilkem Edge Villas — Khaoya Estate, Eldoret         (4 units)
    3. Wilkem Edge Apartments — Donholm Estate, Nairobi    (8 units)

Idempotent — uses get_or_create for buildings, units, and tenants so
running on top of an existing database (e.g. after seed_wilkem_property)
is safe and only adds what's missing.

Usage (Render Shell):
    python manage.py seed_wilkem_rentals
"""
import datetime as dt
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction


def _normalize_phone(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    return "+" + digits


# ============================================================================
# 1. Wilkem Edge Apartments — Seniors Estate, Eldoret
# ============================================================================

SENIORS_BUILDING = {
    "name": "Wilkem Edge Apartments - Seniors Estate, Eldoret",
    "address": "Seniors Estate, Eldoret",
    "legal_name": "Wilkem Ventures Company Limited",
    "paybill_number": "400222",
    "paybill_account_format": "90290#{unit}",
    "total_floors": 5,
}

# (label, floor, unit_type, classification, rent, descriptor)
SENIORS_UNITS = [
    # Block A (floor 1)
    ("WEA01", 1, "1br", "RESIDENTIAL", 8300, "Unit WEA01"),
    ("WEA02", 1, "1br", "RESIDENTIAL", 9000, "Unit WEA02"),
    ("WEA03", 1, "1br", "RESIDENTIAL", 9000, "Unit WEA03"),
    ("WEA04", 1, "1br", "RESIDENTIAL", 9000, "Unit WEA04"),
    ("WEA05", 1, "bedsitter", "RESIDENTIAL", 6300, "Unit WEA05"),
    ("WEA06", 1, "1br", "RESIDENTIAL", 8300, "Unit WEA06"),
    ("WEA07", 1, "1br", "RESIDENTIAL", 8300, "Unit WEA07"),
    ("WEA08", 1, "1br", "RESIDENTIAL", 9000, "Unit WEA08"),
    ("WEA09", 1, "bedsitter", "RESIDENTIAL", 5000, "Unit WEA09"),
    ("WEA10", 1, "1br", "RESIDENTIAL", 9000, "Unit WEA10"),
    ("WEA11", 1, "1br", "RESIDENTIAL", 9000, "Unit WEA11"),
    # Block B (floor 2)
    ("WEB01", 2, "1br", "RESIDENTIAL", 9000, "Unit WEB01"),
    ("WEB02", 2, "1br", "RESIDENTIAL", 8300, "Unit WEB02"),
    ("WEB03", 2, "1br", "RESIDENTIAL", 8300, "Unit WEB03"),
    ("WEB04", 2, "1br", "RESIDENTIAL", 8300, "Unit WEB04"),
    ("WEB05", 2, "bedsitter", "RESIDENTIAL", 7000, "Unit WEB05"),
    ("WEB06", 2, "1br", "RESIDENTIAL", 8300, "Unit WEB06"),
    ("WEB07", 2, "1br", "RESIDENTIAL", 8300, "Unit WEB07"),
    ("WEB08", 2, "1br", "RESIDENTIAL", 8300, "Unit WEB08"),
    ("WEB09", 2, "bedsitter", "RESIDENTIAL", 5000, "Unit WEB09"),
    ("WEB10", 2, "1br", "RESIDENTIAL", 8300, "Unit WEB10"),
    ("WEB11", 2, "1br", "RESIDENTIAL", 8300, "Unit WEB11"),
    # Block C (floor 3)
    ("WEC01", 3, "1br", "RESIDENTIAL", 8300, "Unit WEC01"),
    ("WEC02", 3, "1br", "RESIDENTIAL", 8300, "Unit WEC02"),
    ("WEC03", 3, "1br", "RESIDENTIAL", 8300, "Unit WEC03"),
    ("WEC04", 3, "1br", "RESIDENTIAL", 9000, "Unit WEC04"),
    ("WEC05", 3, "bedsitter", "RESIDENTIAL", 7000, "Unit WEC05"),
    ("WEC06", 3, "1br", "RESIDENTIAL", 8300, "Unit WEC06"),
    ("WEC07", 3, "1br", "RESIDENTIAL", 9000, "Unit WEC07"),
    ("WEC08", 3, "1br", "RESIDENTIAL", 8300, "Unit WEC08"),
    ("WEC09", 3, "bedsitter", "RESIDENTIAL", 5000, "Unit WEC09"),
    ("WEC10", 3, "1br", "RESIDENTIAL", 9000, "Unit WEC10"),
    ("WEC11", 3, "1br", "RESIDENTIAL", 8300, "Unit WEC11"),
    # Block D (floor 4)
    ("WED01", 4, "1br", "RESIDENTIAL", 8300, "Unit WED01"),
    ("WED02", 4, "1br", "RESIDENTIAL", 8300, "Unit WED02"),
    ("WED03", 4, "1br", "RESIDENTIAL", 9000, "Unit WED03"),
    ("WED04", 4, "1br", "RESIDENTIAL", 8300, "Unit WED04"),
    ("WED05", 4, "bedsitter", "RESIDENTIAL", 6300, "Unit WED05"),
    ("WED06", 4, "1br", "RESIDENTIAL", 8300, "Unit WED06"),  # vacant
    ("WED07", 4, "1br", "RESIDENTIAL", 9000, "Unit WED07"),
    ("WED08", 4, "1br", "RESIDENTIAL", 8300, "Unit WED08"),
    ("WED09", 4, "bedsitter", "RESIDENTIAL", 5000, "Unit WED09"),
    ("WED10", 4, "1br", "RESIDENTIAL", 8300, "Unit WED10"),
    ("WED11", 4, "1br", "RESIDENTIAL", 9000, "Unit WED11"),
    # Penthouse
    ("WEP02", 5, "2br", "RESIDENTIAL", 12300, "Unit WEP02 — Penthouse"),
    # Ground-floor shops (floor 0)
    ("WEG01", 0, "shop", "BUSINESS", 10300, "Unit WEG01 — Bakery"),
    ("WEG02", 0, "shop", "BUSINESS",  6300, "Unit WEG02"),  # vacant
    ("WEG03", 0, "shop", "BUSINESS",  6300, "Unit WEG03"),
    ("WEG04", 0, "shop", "BUSINESS",  6300, "Unit WEG04"),
    ("WEG05", 0, "shop", "BUSINESS",  6300, "Unit WEG05"),  # vacant
    ("WEG06", 0, "shop", "BUSINESS",  3500, "Unit WEG06"),
    ("WEG07", 0, "shop", "BUSINESS",  6500, "Unit WEG07"),
    ("WEG12", 0, "shop", "BUSINESS",  5000, "Unit WEG12"),
    ("WEG22", 0, "shop", "BUSINESS",  5000, "Unit WEG22 — Kinyozi"),
]

# (unit_label, full_name, kra_pin_or_id, phone, rent, deposit, move_in)
SENIORS_TENANTS = [
    # Block A
    ("WEA01", "Sarah & Hussein Hamisi",     "A007323744P", "0726012481", 8300, 8000, "2024-01-01"),
    ("WEA02", "Faith Jepchirchir Kipya",     "39189383",    "0729144710", 9000, 9000, "2024-01-01"),
    ("WEA03", "Tabitha Saikwa",              "A015390647P", "0790727551", 9000, 9000, "2024-01-01"),
    ("WEA04", "Elvin Shilaho",               "",            "0724500419", 9000, 9000, "2024-01-01"),
    ("WEA05", "Brigid Amanda",               "38084491",    "0115478025", 6300, 6000, "2024-01-01"),
    ("WEA06", "Boniface Kioko",              "A005233422D", "0724995640", 8300, 8000, "2024-01-01"),  # Residential
    ("WEA07", "Wilberforce Mwanga",          "A007506193G", "0728687974", 8300, 8000, "2024-01-01"),
    ("WEA08", "Caleb Onyango Akongo",        "",            "0710926589", 9000, 9000, "2024-01-01"),
    ("WEA09", "Diana Ochola",                "",            "0102574415", 5000, 5000, "2024-01-01"),
    ("WEA10", "Jael Chebichi Bittok",        "A019241053F", "0715813493", 9000, 9000, "2024-01-01"),
    ("WEA11", "Victor Odido Wandera",        "A012618483I", "0741022249", 9000, 9000, "2024-01-01"),
    # Block B
    ("WEB01", "Kevin Inganga",               "",            "0715175997", 9000, 9000, "2024-01-01"),
    ("WEB02", "Joseph Simiyu Walukanah",     "A017770951A", "0719384235", 8300, 8000, "2024-01-01"),
    ("WEB03", "Beatrice Okumu Adhiambo",     "A005231068I", "0723678873", 8300, 8000, "2024-01-01"),
    ("WEB04", "Simon Murambi",               "A010119493V", "0726716337", 8300, 8000, "2024-01-01"),
    ("WEB05", "Shirley Tonui",               "",            "0707913192", 7000, 7000, "2024-01-01"),
    ("WEB06", "Brian Marube Kinanga",        "A010138736N", "0727107446", 8300, 8000, "2024-01-01"),
    ("WEB07", "Clinton Oloo Onyango",        "A011034154D", "0796330157", 8300, 8000, "2024-01-01"),
    ("WEB08", "Aron Mutai",                  "",            "0724373033", 8300, 8000, "2024-01-01"),
    ("WEB09", "Nassir Juma",                 "",            "0116800697", 5000, 5000, "2024-01-01"),
    ("WEB10", "Alice Babu Boro",             "",            "0725576642", 8300, 8000, "2024-01-01"),
    ("WEB11", "John Mboku Omega",            "A013451438H", "0746772982", 8300, 8000, "2024-01-01"),
    # Block C
    ("WEC01", "Sharon & Alex Rono",          "A010966140X", "0716444709", 8300, 8000, "2024-01-01"),
    ("WEC02", "Erick Odhiambo",              "",            "0785979305", 8300, 8000, "2024-01-01"),
    ("WEC03", "Mercyline Gibson",            "A008054252M", "0727765567", 8300, 8000, "2024-01-01"),
    ("WEC04", "Boniface Mwangi",             "",            "0739044662", 9000, 9000, "2024-01-01"),
    ("WEC05", "Sheldon Mutai",               "",            "0707575747", 7000, 7000, "2024-01-01"),
    ("WEC06", "Enock Nyagoto Kombo",         "A010889930J", "0701053378", 8300, 8000, "2024-01-01"),
    ("WEC07", "Edward Muthee",               "A007497376O", "0718242633", 9000, 8000, "2024-01-01"),
    ("WEC08", "Viola Tuwei",                 "A003859567V", "0720699440", 8300, 8000, "2024-01-01"),
    ("WEC09", "Harrison Njoroge Chege",      "A013593173Y", "0793631130", 5000, 4000, "2024-01-01"),
    ("WEC10", "James Wekati Ambani",         "",            "0727132820", 9000, 9000, "2024-01-01"),
    ("WEC11", "Naom Chebet Mutai",           "A016853018Q", "0113223994", 8300, 8000, "2024-01-01"),
    # Block D
    ("WED01", "Noah Omollo",                 "A009216198G", "0721280719", 8300, 8000, "2024-01-01"),
    ("WED02", "Titus Odhiambo",              "",            "0716311210", 8300, 8000, "2024-01-01"),
    ("WED03", "Kevin Gekonge",               "",            "0727480635", 9000, 9000, "2024-01-01"),
    ("WED04", "Emmanuel Jefwa",              "A007100542W", "0705791349", 8300, 8000, "2024-01-01"),
    ("WED05", "Joseph Kiminja Mokare",       "A004385756K", "0718262738", 6300, 6000, "2024-01-01"),
    # WED06 vacant
    ("WED07", "Anthony Too",                 "A009684964P", "0758021140", 9000, 8000, "2024-01-01"),
    ("WED08", "Walter Amos Luzinga",         "A005759965X", "0743081993", 8300, 8000, "2024-01-01"),
    ("WED09", "Titus Wanjala",               "",            "0722834346", 5000, 5000, "2024-01-01"),
    ("WED10", "Dennis Charamba",             "A017750956D", "0104336219", 8300, 8000, "2024-01-01"),
    ("WED11", "Kipkoech Ngetich",            "",            "0742531969", 9000, 9000, "2024-01-01"),
    # Penthouse
    ("WEP02", "Lilian Muli",                 "",            "0704612677", 12300, 12000, "2024-01-01"),
    # Ground-floor shops
    ("WEG01", "Wycliffe Barasa",             "A008354765C", "0706515870", 10300, 12000, "2024-01-01"),  # Bakery
    ("WEG03", "Faith J Kimutai",             "A013905938G", "0706300831",  6300, 10000, "2024-01-01"),
    ("WEG04", "Boniface Kioko",              "A005233422D", "0724995640",  6300, 12000, "2024-01-01"),  # Shop (different unit from WEA06)
    ("WEG06", "Andrew Mwangi",               "A012150923W", "0722254461",  3500,  7000, "2024-01-01"),  # Shop
    ("WEG07", "Ruth Matendechere Kulundu",   "A01553985L",  "0724568501",  6500, 12000, "2024-01-01"),
    ("WEG12", "Angela Wanyonyi",             "A006226294B", "0741357229",  5000, 10000, "2024-01-01"),
    ("WEG22", "Kevin Awino",                 "",            "0721546915",  5000, 10000, "2024-01-01"),  # Kinyozi (barber)
]


# ============================================================================
# 2. Wilkem Edge Villas — Khaoya Estate, Eldoret
# ============================================================================

KHAOYA_BUILDING = {
    "name": "Wilkem Edge Villas - Khaoya Estate, Eldoret",
    "address": "Khaoya Estate, Eldoret",
    "legal_name": "Wilkem Ventures Company Limited",
    "paybill_number": "400222",
    "paybill_account_format": "90290#{unit}",
    "total_floors": 1,
}

KHAOYA_UNITS = [
    ("WK01", 0, "2br", "RESIDENTIAL", 9500, "Villa WK01"),
    ("WK02", 0, "2br", "RESIDENTIAL", 9500, "Villa WK02"),
    ("WK03", 0, "2br", "RESIDENTIAL", 9500, "Villa WK03"),
    ("WK04", 0, "2br", "RESIDENTIAL", 9500, "Villa WK04"),
]

KHAOYA_TENANTS = [
    ("WK01", "Lionel Nyangau Obino", "A006032628G", "0701834008", 9500, 9000, "2024-01-01"),
    ("WK02", "Kefa Moracha",         "A008304249Q", "0728814767", 9500, 9000, "2024-01-01"),
    ("WK03", "Duncan Jaber Owino",   "A009942803X", "0728539410", 9500, 9000, "2024-01-01"),
    ("WK04", "John Mwangi Maina",    "A005921142M", "0729572137", 9500,    0, "2024-01-01"),
]


# ============================================================================
# 3. Wilkem Edge Apartments — Donholm Estate, Nairobi
# ============================================================================

DONHOLM_BUILDING = {
    "name": "Wilkem Edge Apartments - Donholm Estate, Nairobi",
    "address": "Donholm Estate, Nairobi",
    "legal_name": "Wilkem Ventures Company Limited",
    "paybill_number": "400222",
    "paybill_account_format": "90290#{unit}",
    "total_floors": 4,
}

DONHOLM_UNITS = [
    ("WD1A", 1, "2br", "RESIDENTIAL", 15000, "Unit WD1A"),
    ("WD1B", 1, "2br", "RESIDENTIAL", 20000, "Unit WD1B"),
    ("WD2A", 2, "2br", "RESIDENTIAL", 20000, "Unit WD2A"),
    ("WD2B", 2, "2br", "RESIDENTIAL", 20000, "Unit WD2B"),
    ("WD3A", 3, "2br", "RESIDENTIAL", 20000, "Unit WD3A"),
    ("WD3B", 3, "2br", "RESIDENTIAL", 20000, "Unit WD3B"),
    ("WD4A", 4, "2br", "RESIDENTIAL", 20000, "Unit WD4A"),
    ("WD4B", 4, "2br", "RESIDENTIAL", 18000, "Unit WD4B"),
]

DONHOLM_TENANTS = [
    ("WD1A", "Mercy Murunga",         "A005544221L", "0711406924", 15000, 14000, "2024-01-01"),
    ("WD1B", "Nicholas Kute",         "A002935955M", "0720743211", 20000, 16000, "2024-01-01"),
    ("WD2A", "Festus Kibet Kirui",    "A010111081S", "0798663646", 20000, 20000, "2024-01-01"),
    ("WD2B", "Emmah Mueni",           "A014706715T", "0702723537", 20000, 18000, "2024-01-01"),
    ("WD3A", "Zachary Bwonda",        "A007523148T", "0718080157", 20000, 20000, "2024-01-01"),
    ("WD3B", "Jamro Company Limited", "P051440004G", "0723789696", 20000, 16000, "2024-01-01"),  # Company
    ("WD4A", "Justine Masila",        "A005574951D", "0723667673", 20000, 16000, "2024-01-01"),
    ("WD4B", "Christine Mukonyo",     "A005720070O", "0726483602", 18000,     0, "2024-01-01"),
]


# ============================================================================
# Command
# ============================================================================

PROPERTIES = [
    ("Seniors Estate (Eldoret)", SENIORS_BUILDING, SENIORS_UNITS, SENIORS_TENANTS),
    ("Khaoya Villas (Eldoret)",  KHAOYA_BUILDING,  KHAOYA_UNITS,  KHAOYA_TENANTS),
    ("Donholm (Nairobi)",        DONHOLM_BUILDING, DONHOLM_UNITS, DONHOLM_TENANTS),
]


class Command(BaseCommand):
    help = "Seed the 3 rental properties (Seniors, Khaoya, Donholm) — idempotent."

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.buildings.models import Building, Unit, UnitStatus
        from apps.tenants.models import Tenant, TenantStatus

        grand_units = 0
        grand_tenants = 0

        for label, building_data, units, tenants in PROPERTIES:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n— {label} —"))

            building, b_created = Building.objects.get_or_create(
                name=building_data["name"],
                defaults={k: v for k, v in building_data.items() if k != "name"},
            )
            self.stdout.write(
                f"  Building: {'created' if b_created else 'found'} — {building.name}"
            )

            new_units = 0
            for u_label, floor, unit_type, classification, rent, descriptor in units:
                _, created = Unit.objects.get_or_create(
                    building=building, label=u_label,
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
            self.stdout.write(f"  Units: {new_units} new (total in seed: {len(units)})")
            grand_units += new_units

            new_tenants = 0
            for u_label, full_name, id_or_kra, phone, rent, deposit, move_in in tenants:
                try:
                    unit = Unit.objects.get(building=building, label=u_label)
                except Unit.DoesNotExist:
                    self.stdout.write(self.style.ERROR(
                        f"    Unit {u_label} not found — skipping {full_name}"
                    ))
                    continue

                # Split the name into first / last
                name_parts = full_name.strip().split(maxsplit=1)
                first = name_parts[0] if name_parts else "Tenant"
                last = name_parts[1] if len(name_parts) > 1 else u_label

                # id_number: real ID > KRA PIN > synthetic
                id_value = (id_or_kra or "").strip()
                kra_value = id_value if id_value.upper().startswith(("A", "P")) else ""
                if not id_value:
                    id_value = f"RES-{u_label}"

                _, created = Tenant.objects.get_or_create(
                    id_number=id_value,
                    defaults={
                        "first_name": first[:100],
                        "last_name": last[:100],
                        "phone": _normalize_phone(phone),
                        "kra_pin": kra_value,
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
            self.stdout.write(f"  Tenants: {new_tenants} new (total in seed: {len(tenants)})")
            grand_tenants += new_tenants

        self.stdout.write(self.style.SUCCESS(
            f"\nDone — {grand_units} new units, {grand_tenants} new tenants across 3 properties."
        ))
