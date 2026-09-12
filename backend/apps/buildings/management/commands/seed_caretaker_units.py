"""
Give each non-rental property a unit and a caretaker to occupy it.

The farms and the Karen residence were seeded as buildings with no units at all
(see ``seed_special_properties``), because neither lets space to anybody. Each
of them is nonetheless lived on: a caretaker occupies the house as part of their
job. With no unit and no tenant, that occupancy was nowhere on the system — no
contact details, no deposit, no record of who is on the property.

The occupancy is recorded as a tenancy at zero rent with ``is_billable`` off,
which keeps it out of the monthly rent run, both reminder jobs and the monthly
statements. Zero rent alone would NOT do that: the rent run would raise a 0.00
arrears row every month, and the reminder jobs walk ACTIVE tenants rather than
unpaid ones. See ``apps.payments.tasks.billable_active_tenants``.

Unit labels carry the building code, as every label must — they are unique
across the whole portfolio so a paybill reference resolves to exactly one unit:

    FSCH   Wilkem Navillus Farm, Soy Eldoret
    FMNCH  Wilkem Farm, Mwongori Nyamira
    FNNCH  Wilkem Farm, Nyariacho Nyamira
    KNCH   Wilkem Residence, The Baobab Karen

Idempotent: re-running matches on the unit label and leaves an existing
caretaker alone, so it is safe to run again once the real names are known.

Caretakers are seeded with a placeholder identity — the same 'PENDING-<unit>'
convention ``sync_matasia_commercial`` uses — because ``id_number`` is unique
and required. Fill the real details in from the dashboard, or pass them here:

    python manage.py seed_caretaker_units --dry-run
    python manage.py seed_caretaker_units
    python manage.py seed_caretaker_units --caretaker FSCH "Joseph Kiplagat" 0712345678 12345678
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.tenants.models import Tenant, TenantStatus

# (building code, unit label, surname used for the placeholder caretaker)
CARETAKER_UNITS = [
    ("FS",  "FSCH",  "Soy"),
    ("FMN", "FMNCH", "Mwongori"),
    ("FNN", "FNNCH", "Nyariacho"),
    ("KN",  "KNCH",  "Karen"),
]

PLACEHOLDER_ID_PREFIX = "PENDING-"


class Command(BaseCommand):
    help = "Create a caretaker unit + rent-free caretaker tenancy on each farm and at Karen."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change, then roll back.")
        parser.add_argument("--move-in", default=None,
                            help="Move-in date for new caretaker tenancies (YYYY-MM-DD). "
                                 "Defaults to today.")
        parser.add_argument(
            "--caretaker", nargs=4, action="append", default=[],
            metavar=("UNIT", "FULL_NAME", "PHONE", "ID_NUMBER"),
            help="Real details for one caretaker. Repeatable.",
        )

    def handle(self, *args, **opts):
        move_in = date.fromisoformat(opts["move_in"]) if opts["move_in"] else date.today()
        overrides = {c[0].upper(): tuple(c[1:]) for c in opts["caretaker"]}

        known = {label for _, label, _ in CARETAKER_UNITS}
        unknown = set(overrides) - known
        if unknown:
            self.stderr.write(self.style.ERROR(
                f"Unknown caretaker unit(s): {', '.join(sorted(unknown))}. "
                f"Expected one of: {', '.join(sorted(known))}."
            ))
            return

        units_created = tenants_created = skipped = 0
        missing = []

        with transaction.atomic():
            for code, label, placeholder_surname in CARETAKER_UNITS:
                building = Building.objects.filter(code=code).first()
                if building is None:
                    missing.append(code)
                    continue

                unit, made = Unit.objects.get_or_create(
                    label=label,
                    defaults={
                        "building": building,
                        "floor": 0,
                        "unit_type": "single",
                        "classification": UnitClassification.RESIDENTIAL,
                        # Rent-free: the caretaker occupies as part of the job,
                        # so there is no rent to charge and nothing to arrear.
                        "monthly_rent": 0,
                        "statement_descriptor": f"Caretaker's house — {building.name}",
                        "notes": "Caretaker's house. Not let — occupied as staff housing.",
                    },
                )
                if made:
                    units_created += 1
                    self.stdout.write(f"  + unit {label} on {code} {building.name}")

                occupied = Tenant.objects.filter(unit=unit).exclude(
                    status=TenantStatus.MOVED_OUT
                ).exists()
                if occupied:
                    skipped += 1
                    self.stdout.write(f"    = {label} already has a caretaker on record")
                    continue

                full_name, phone, id_number = overrides.get(
                    label,
                    (f"Caretaker {placeholder_surname}", "", f"{PLACEHOLDER_ID_PREFIX}{label}"),
                )
                first, _, last = full_name.partition(" ")

                Tenant.objects.create(
                    first_name=first,
                    last_name=last or placeholder_surname,
                    id_number=id_number,
                    phone=phone,
                    unit=unit,
                    monthly_rent=0,
                    deposit_paid=0,
                    # Blank means "use the rule", and the rule is one month's
                    # rent — zero here — so the deposit card reports no
                    # shortfall rather than chasing money nobody owes.
                    agreed_deposit=None,
                    move_in_date=move_in,
                    status=TenantStatus.ACTIVE,
                    is_billable=False,
                    notes="Caretaker housed on site as part of their employment. Not charged "
                          "rent — excluded from billing, reminders and statements.",
                )
                tenants_created += 1
                flag = "" if label in overrides else "   [placeholder — fill in real details]"
                self.stdout.write(f"  + caretaker {full_name} -> {label}{flag}")

                # A caretaker's house is occupied, not vacant. Set it directly
                # rather than through buildings.services.move_in, which raises
                # on a unit an earlier run already occupied. OCCUPIED_PAID is
                # the truthful state when no rent is owed for the period.
                if unit.status != UnitStatus.OCCUPIED_PAID:
                    unit.status = UnitStatus.OCCUPIED_PAID
                    unit.save(update_fields=["status", "updated_at"])

            if opts["dry_run"]:
                transaction.set_rollback(True)

        if missing:
            self.stdout.write(self.style.WARNING(
                f"\nNo building found for code(s): {', '.join(missing)}. "
                f"Run `python manage.py seed_special_properties` first."
            ))

        summary = (f"\n{units_created} unit(s) created, {tenants_created} caretaker(s) created, "
                   f"{skipped} already on record.")
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING(summary + "   [DRY RUN — rolled back]"))
            return

        self.stdout.write(self.style.SUCCESS(summary))
        pending = Tenant.objects.filter(
            is_billable=False, id_number__startswith=PLACEHOLDER_ID_PREFIX
        ).count()
        if pending:
            self.stdout.write(
                f"{pending} caretaker(s) still carry a placeholder ID and no phone number. "
                f"Edit them from the dashboard, or re-run with --caretaker."
            )
