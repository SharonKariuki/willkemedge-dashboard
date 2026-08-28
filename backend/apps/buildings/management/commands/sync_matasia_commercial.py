"""
Bring Matasia Commercial (building code MC) in line with the official
"TENANT DETAILS AS ON 21-07-2026" rent roll.

Source of truth
---------------
The ROLL table below is transcribed from the 21-07-2026 statement screenshots
supplied by the owner on 2026-08-01. It deliberately does NOT read the
"Wilkem Edge Business Arcade - Matasia Commercial & Residential Properties.xlsx"
sitting in the repo root: that workbook is an OLDER revision and disagrees with
the statement on who occupies what (it shows MCF03 vacant with Elimisha on
MCF05, and has no MCG06/MCG09 rows at all). Loading it would move a live
tenancy. If a newer workbook arrives, re-transcribe here rather than pointing
this command at the file.

What it does
------------
  * Renames the five legacy-labelled units (G-02, G-04, G-05, F-03, F-13B) to
    their coding-scheme codes. NO UnitAlias rows are created — owner policy
    (2026-08-01) is that tenants quote the exact code and anything else goes to
    the unmatched queue for manual assignment.
  * Creates the units the roll lists that are missing, and their tenants.
  * Corrects rent where the roll and the database disagree.

Rent stored on Unit/Tenant is the VAT-EXCLUSIVE base ("Monthly Rent" column);
BUSINESS classification makes the statement engine add 16% VAT on top. The
roll's "Rent + 16% VAT" column is therefore NOT what gets stored — it is used
only to cross-check each row, and a row whose VAT doesn't reconcile is
reported rather than silently loaded.

Idempotent and DRY-RUN by default. Nothing is written without --apply.

Usage:
    python manage.py sync_matasia_commercial
    python manage.py sync_matasia_commercial --apply
"""
import datetime as dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

BUILDING_CODE = "MC"

# Placeholder move-in for tenants the roll introduces: the statement date. The
# roll carries no lease dates, so this is explicitly a stand-in to be corrected
# from the lease file — never treat it as the real commencement date.
DEFAULT_MOVE_IN = dt.date(2026, 7, 21)

# Legacy label -> coding-scheme code. F-13B maps to MCF14, NOT MCF13: on the
# roll MCF13 is NKM Advocates and MCF14 is GeoTruth Consult, and F-13B holds
# GeoTruth. Getting this backwards would hand GeoTruth another firm's unit.
RENAMES = {
    "G-02": "MCG02",
    "G-04": "MCG04",
    "G-05": "MCG05",
    "F-03": "MCF03",
    "F-13B": "MCF14",
}

# (unit, floor, tenant, contact person, phone, KRA PIN, base rent, VAT on roll)
# vat=None means the roll leaves the VAT cell blank for that row.
ROLL = [
    ("MCG01", 0, "Lecias Enterprises Limited", "Dennis Kerosi", "0733624892", "P052438828Z", "24000", "3840"),
    ("MCG02", 0, "Glow by Ellie Salon", "Philip Njenga", "0710602459", "A004392923Z", "22500", "0"),
    ("MCG03", 0, "Glow by Ellie Barber Shop", "Philip Njenga", "0710602459", "A004392923Z", "18000", "2880"),
    ("MCG04", 0, "Fortify Solutions Limited", "Hellen Chege", "0722434022", "P051696399H", "45000", "7200"),
    ("MCG05", 0, "Sidai Lonestar Healthcare", "David Chibeka", "0722301981", "P052201098W", "86500", "13840"),
    ("MCG06", 0, "Sidai Lonestar Healthcare", "David Chibeka", "0722301982", "P052201098W", "0", None),
    ("MCG07", 0, None, "", "", "", "0", None),
    ("MCG08", 0, "Mavin House Wares", "Violet Nafula Juma", "0715454643", "A005802847Z", "57800", "9248"),
    ("MCG09", 0, "Mavin House Wares", "Violet Nafula Juma", "0715454644", "A005802847Z", "0", None),
    ("MCG10", 0, "Shamir Car Wash & Eatery", "Stephen Kamau", "0728396204", "A005402165M", "25000", "4000"),
    ("MCF01", 1, None, "", "", "", "0", None),
    ("MCF02", 1, None, "", "", "", "0", None),
    ("MCF03", 1, "Elimisha Limited", "Andrew Mwaura", "0720772330", "P051243390B", "22500", "3600"),
    ("MCF04", 1, "Wilkem Ventures Co. Ltd.", "Wilkem Ventures Co. Ltd. (Mgt Office)", "", "", "25000", "4000"),
    ("MCF05", 1, None, "", "", "", "0", None),
    ("MCF06", 1, None, "", "", "", "0", None),
    ("MCF07", 1, None, "", "", "", "0", None),
    ("MCF08", 1, None, "", "", "", "0", None),
    ("MCF09", 1, None, "", "", "", "0", None),
    ("MCF10", 1, None, "", "", "", "0", None),
    ("MCF11", 1, None, "", "", "", "0", None),
    ("MCF12", 1, "Sidai Healthcare Office", "David Chibeka", "0722301981", "P052201098W", "50655", "8105"),
    ("MCF13", 1, "NKM Advocates", "Agnes Nyawira Kionga", "0707329013", "A004575535A", "24000", "3840"),
    ("MCF14", 1, "GeoTruth Consult", "Kefa Ouma Ojwando", "0731440843", "P052294406W", "22500", "3600"),
    ("MCF15", 1, None, "", "", "", "0", None),
    ("MCF16", 1, None, "", "", "", "0", None),
]

VAT_RATE = Decimal("0.16")


def _split_name(name: str) -> tuple[str, str]:
    """Company names are stored as first_name + last_name (last word last)."""
    parts = name.split()
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def _e164(phone: str, unit_code: str) -> str:
    """Normalise to +254…, or a non-numeric placeholder when the roll has none.

    Tenant.phone is required. The placeholder is deliberately NOT digits: the
    payment matcher's phone fallback normalises to bare digits, so a
    'PENDING-…' value can never collide with a real payer MSISDN and misroute
    someone's money.
    """
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        return f"PENDING-{unit_code}"
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    return "+" + digits


class Command(BaseCommand):
    help = "Sync Matasia Commercial units/tenants to the 21-07-2026 rent roll. Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write the changes. Without this nothing is saved.")

    def handle(self, *args, **opts):
        from apps.buildings.models import (
            Building, Unit, UnitClassification, UnitStatus,
        )
        from apps.tenants.models import Tenant, TenantStatus

        apply = opts["apply"]

        try:
            building = Building.objects.get(code=BUILDING_CODE)
        except Building.DoesNotExist as err:
            raise CommandError(f"No building with code {BUILDING_CODE!r}.") from err

        # --- Cross-check the roll's own arithmetic before touching anything ---
        vat_notes = []
        for unit_code, _f, tenant, _c, _p, _k, rent, vat in ROLL:
            if tenant is None or vat is None:
                continue
            expected = (Decimal(rent) * VAT_RATE).quantize(Decimal("1"))
            if abs(Decimal(vat) - expected) > 1:
                vat_notes.append(f"{unit_code}: roll shows VAT {vat} on rent {rent} (16% would be {expected})")

        plan_rename, plan_new_unit, plan_new_tenant, plan_rent = [], [], [], []

        existing = {u.label.upper(): u for u in building.units.all()}

        # 1. Renames (legacy label -> scheme code).
        for old, new in RENAMES.items():
            unit = existing.get(old.upper())
            if unit is None:
                continue
            clash = Unit.objects.filter(label__iexact=new).exclude(pk=unit.pk).first()
            if clash:
                raise CommandError(
                    f"Cannot rename {old} -> {new}: {new} already exists (unit #{clash.pk})."
                )
            plan_rename.append((unit, old, new))

        # Label view AFTER the renames, so step 2 doesn't re-create a renamed unit.
        after_rename = {RENAMES.get(lbl, lbl).upper() for lbl in existing}

        # 2. Missing units, and 3. tenants / rent corrections.
        by_code = {u[0]: u for u in ROLL}
        for unit_code, floor, tenant_name, contact, phone, kra, rent, _vat in ROLL:
            if unit_code.upper() not in after_rename:
                plan_new_unit.append((unit_code, floor, tenant_name, rent))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{building.name} ({BUILDING_CODE}) — sync to 21-07-2026 roll"
        ))

        if plan_rename:
            self.stdout.write("\nRelabel (no aliases kept — owner policy):")
            for _u, old, new in plan_rename:
                self.stdout.write(f"  {old:>6}  ->  {new}")

        if plan_new_unit:
            occupied = [p for p in plan_new_unit if p[2]]
            vacant = [p for p in plan_new_unit if not p[2]]
            self.stdout.write(f"\nCreate {len(plan_new_unit)} unit(s) "
                              f"({len(occupied)} occupied, {len(vacant)} vacant):")
            for code, _fl, tname, rent in occupied:
                self.stdout.write(f"  {code:<7} {tname:<32} rent {rent:>9}")
            if vacant:
                self.stdout.write(f"  vacant: {', '.join(c for c, _f, _t, _r in vacant)}")

        if vat_notes:
            self.stdout.write(self.style.WARNING("\n[REVIEW] VAT rows that don't reconcile at 16%:"))
            for note in vat_notes:
                self.stdout.write(f"  {note}")

        if not apply:
            self.stdout.write(self.style.WARNING(
                "\nDRY-RUN — nothing written. Re-run with --apply."
            ))
            self._report_rent_drift(building, by_code)
            return

        created_units = created_tenants = renamed = rent_fixed = 0
        with transaction.atomic():
            for unit, _old, new in plan_rename:
                unit.label = new
                unit.full_clean()
                unit.save(update_fields=["label", "updated_at"])
                renamed += 1

            for unit_code, floor, tenant_name, contact, phone, kra, rent, _vat in ROLL:
                unit = Unit.objects.filter(label__iexact=unit_code).first()
                if unit is None:
                    unit = Unit(
                        building=building,
                        label=unit_code,
                        floor=floor,
                        unit_type="shop",
                        classification=UnitClassification.BUSINESS,
                        monthly_rent=Decimal(rent),
                        status=UnitStatus.VACANT,
                    )
                    unit.full_clean()
                    unit.save()
                    created_units += 1

                if tenant_name is None:
                    continue

                tenant = Tenant.objects.filter(
                    unit=unit, status=TenantStatus.ACTIVE
                ).first()
                if tenant is None:
                    first, last = _split_name(tenant_name)
                    tenant = Tenant(
                        first_name=first,
                        last_name=last,
                        id_number=f"PENDING-{unit_code}",
                        kra_pin=kra,
                        phone=_e164(phone, unit_code),
                        care_of=contact,
                        unit=unit,
                        monthly_rent=Decimal(rent),
                        deposit_paid=Decimal("0"),
                        move_in_date=DEFAULT_MOVE_IN,
                        status=TenantStatus.ACTIVE,
                    )
                    tenant.full_clean()
                    tenant.save()
                    created_tenants += 1
                elif tenant.monthly_rent != Decimal(rent):
                    self.stdout.write(
                        f"  rent {unit_code}: {tenant.monthly_rent} -> {rent} ({tenant})"
                    )
                    tenant.monthly_rent = Decimal(rent)
                    tenant.save(update_fields=["monthly_rent", "updated_at"])
                    rent_fixed += 1

                if unit.monthly_rent != Decimal(rent):
                    unit.monthly_rent = Decimal(rent)
                    unit.save(update_fields=["monthly_rent", "updated_at"])
                if unit.status == UnitStatus.VACANT:
                    unit.status = UnitStatus.OCCUPIED_UNPAID
                    unit.save(update_fields=["status", "updated_at"])

        self.stdout.write(self.style.SUCCESS(
            f"\nDone: {renamed} relabelled, {created_units} unit(s) created, "
            f"{created_tenants} tenant(s) created, {rent_fixed} rent(s) corrected."
        ))
        self.stdout.write(
            "New tenants carry id_number 'PENDING-<unit>', deposit 0 and move-in "
            f"{DEFAULT_MOVE_IN} — the roll has none of these. Correct from the lease file."
        )

    def _report_rent_drift(self, building, by_code):
        """Show rents that differ between the database and the roll."""
        from apps.tenants.models import Tenant, TenantStatus

        rows = []
        for tenant in Tenant.objects.filter(
            unit__building=building, status=TenantStatus.ACTIVE
        ).select_related("unit"):
            code = RENAMES.get(tenant.unit.label, tenant.unit.label)
            entry = by_code.get(code)
            if entry and tenant.monthly_rent != Decimal(entry[6]):
                rows.append((code, tenant, tenant.monthly_rent, entry[6]))
        if rows:
            self.stdout.write(self.style.WARNING("\nRent differs from the roll:"))
            for code, tenant, have, want in rows:
                self.stdout.write(f"  {code:<7} {tenant}: {have} -> {want}")
