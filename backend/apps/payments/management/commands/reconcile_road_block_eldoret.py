"""
Bring Wilkem Edge Apartments - Road Block, Eldoret into line with the
landlord's Road Block rent-roll spreadsheet (two-image statement supplied
21 Aug 2026).

Two separate problems on this property, both fixed here:

1. TENANT-UNIT MISMATCH (a swap chain, not random corruption)
   Six units carry the wrong tenant, and three of the six are simply each
   other's rightful occupant:

     RB304 has Boniface Mwangi        -> belongs on RB107
     RB202 has Joseph Simiyu Walukanah -> belongs on RB304
     RB201 has Kevin Inganga           -> belongs on RB302
     RB107 has Wilberforce Mwanga      -> not on the statement at all
     RB203 has Beatrice Okumu Adhiambo -> not on the statement at all
     RB208 has Aron Mutai              -> not on the statement at all
     RB302 has Erick Odhiambo          -> not on the statement at all
     RB004 has Kevin Awino             -> statement says vacant
     RB007 has Charles Ndungu          -> statement says vacant

   The three displaced tenants who ARE on the statement (Boniface Mwangi,
   Joseph Simiyu Walukanah, Kevin Inganga) move to their correct unit and
   keep their own tenant record (and, critically, their own history —
   Arrears rows follow the tenant, not the unit). The four who are not on
   the statement anywhere (Wilberforce Mwanga, Beatrice Okumu Adhiambo,
   Aron Mutai, Erick Odhiambo) are marked MOVED_OUT rather than deleted —
   their history stays on file for audit, they just stop being billed.
   Four units need a tenant that doesn't exist in the database yet
   (Beryl Alinga, Harun Ndiritu, Mariane Mukabwa, Michael Kalume) and are
   created fresh.

   Because the unit's OWN monthly_rent was apparently set to match whichever
   tenant got wrongly attached to it at import time, three of the six
   swapped units (RB406, RB408, RB409 too, unrelated to the swap) are also
   carrying the wrong base rent. Step 1 corrects every unit's monthly_rent
   to the statement's August figure.

2. NO JULY ARREARS ROW REFLECTS REALITY, NO AUGUST BILLING EXISTS YET
   Same root cause documented in reconcile_matasia_residential: unlike
   Matasia, Road Block DOES already have June and July Arrears rows, but
   they were raised as ordinary monthly charges and never reconciled
   against actual cash received, so they no longer agree with the
   landlord's "Arrears B/F July-2026" column. Rather than guess which
   historical payment went missing and when, this command treats the
   statement's B/F as authoritative: any balance outstanding before July
   is waived with an audit note, and July is rewritten so the rent roll
   CLOSES it on exactly the statement's B/F (owed, zero, or in credit) —
   the same technique reconcile_matasia_residential uses for an opening
   position, adapted to overwrite an existing row instead of skipping when
   one is present.

   Closing on the B/F is not the same as writing the B/F in. July is a
   genuinely billed month in production: it can carry a residual in from
   June and can have taken cash of its own, so the opening charge is
   solved for rather than assumed (see ``_reset_opening``).

   Cash is reconciled the same way. August receipts already exist on the
   live database — the Co-op feed banks them as they arrive — so step 5
   posts only the difference between what is banked and what the statement
   reports, and never removes a receipt that exceeds it.

Two further units — RB109 and RB401 — were let in the database to tenants the
sheet never mentions (Daniel Otieno and Sheila Khaemba Namusonge). The
landlord settled it on 31 Aug 2026: the statement is right and the database is
stale, so step 0b2 re-lets both to the tenant the sheet names. See ``RELET``.

A statement row whose unit is still let to somebody the statement never
mentions is reconciled by neither: it is skipped, and listed under NOT
RECONCILED at the end of the run for the landlord to settle. Only a total
pre-flight failure — not one row on the property resolving — aborts, since
that means the wrong building or the wrong database, not a disagreement about
one unit.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe
(every step is idempotent — it detects and skips work already done).

Usage:
    python manage.py reconcile_road_block_eldoret
    python manage.py reconcile_road_block_eldoret --apply
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.payments.monthly_ledger import OPENING_MARKER

BUILDING_NAME = "Road Block"
JULY_CLOSE = _dt.date(2026, 7, 31)
AUG_POST = _dt.date(2026, 8, 1)   # other charges + payments — no day was given, so
AUG_PAY = _dt.date(2026, 8, 1)    # the 1st is used for both; see chat for the ask.
AUG = (2026, 8)
JUL = (2026, 7)

OPENING_NOTE = (
    f"{OPENING_MARKER} from the 21 Aug 2026 Road Block statement's "
    "'Arrears B/F July-2026' column — not a billed month."
)
CLEARED_NOTE = (
    "Cleared — superseded by the 21 Aug 2026 Road Block statement's "
    "'Arrears B/F July-2026' figure (see the July opening entry)."
)


def D(value):
    return Decimal(str(value))


def _money(value):
    return D(value).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Tenants who are on the statement but currently sit on the WRONG unit in the
# database. Moved to the unit they belong on; nothing else about the tenant
# record changes, including their own Arrears history.
#   tenant id, current (wrong) unit, correct unit
# ---------------------------------------------------------------------------
MOVES = [
    (122, "RB304", "RB107"),   # Boniface Mwangi
    (109, "RB202", "RB304"),   # Joseph Simiyu Walukanah
    (108, "RB201", "RB302"),   # Kevin Inganga
]

# Tenants who are NOT anywhere on the statement. Marked moved out rather than
# reassigned to a guessed unit or deleted.
VACATE = [
    (91, "RB004", "Not on the 21 Aug 2026 Road Block statement (unit shown vacant)"),
    (94, "RB007", "Not on the 21 Aug 2026 Road Block statement (unit shown vacant)"),
    (103, "RB107", "Not on the statement anywhere; RB107 belongs to Boniface Mwangi"),
    (110, "RB203", "Not on the statement anywhere; RB203 belongs to Mariane Mukabwa"),
    (115, "RB208", "Not on the statement anywhere; RB208 belongs to Michael Kalume"),
    (120, "RB302", "Not on the statement anywhere; RB302 belongs to Kevin Inganga"),
]

# Units the statement lists a tenant for who has no record in the database.
#   unit, first name, last name, phone (E.164), kra_pin (blank = none given)
NEW_TENANTS = [
    ("RB201", "Beryl", "Alinga", "+254742434195", ""),
    ("RB202", "Harun", "Ndiritu", "+254716747741", ""),
    ("RB203", "Mariane", "Mukabwa", "+254111739203", ""),
    ("RB208", "Michael", "Kalume", "+254797742172", ""),
]

# Units the statement RE-LETS: the tenant sitting on them in the database is
# not named anywhere on the sheet, and the sheet gives the unit to somebody
# else. The landlord confirmed (31 Aug 2026) that the statement is right and
# the database is stale, so the sitting tenant moves out and the statement's
# tenant takes the unit — moved across if they are already on file, created
# from the sheet's own details if they are not.
#
# Keyed by name rather than by primary key (as MOVES and VACATE are), because
# these two rows were found by reading a production dry-run rather than the
# import, and a pk read off one database is not portable to another.
#
#   unit, tenant sitting on it now (exact full name), incoming phone (E.164),
#   incoming kra_pin  — the last two are used only if the incoming tenant has
#   to be created; "" means the sheet did not give it.
RELET = [
    ("RB109", "Daniel Otieno", "+254102574415", ""),
    ("RB401", "Sheila Khaemba Namusonge", "", ""),
]

# Units the statement shows vacant.
VACANT_UNITS = ["RB002", "RB004", "RB007"]

# ---------------------------------------------------------------------------
# The statement, one row per occupied unit, keyed by Hse Number (the
# correct/target mapping — i.e. after MOVES/VACATE/NEW_TENANTS are applied).
#
#   unit, tenant full name (for the pre-flight check only), b/f, Aug rent,
#   other charges, payment made, statement's own "Rent + Arrears" total,
#   statement's own "Balance Pending"
#
# The last two columns are never written — they are what the statement
# itself printed, held against Aug rent + b/f + other (the formula given)
# purely to flag arithmetic the spreadsheet itself got wrong.
# ---------------------------------------------------------------------------
STATEMENT = [
    ("RB101", "Sarah & Hussein Hamisi",         D(0),     D(8300), D(0),    D(8300),  D(8300),  D(0)),
    ("RB102", "Faith Jepchirchir Kipya",        D(4500),  D(9000), D(225),  D(10000), D(13500), D(3500)),
    ("RB103", "Tabitha Saikwa",                 D(0),     D(9000), D(0),    D(9000),  D(9000),  D(0)),
    ("RB104", "Elvin Shilaho",                  D(9000),  D(9000), D(450),  D(18000), D(18000), D(0)),
    ("RB105", "Brigid Amanda",                  D(6300),  D(6300), D(315),  D(9000),  D(12600), D(3600)),
    ("RB106", "Boniface Kioko",                 D(0),     D(8300), D(0),    D(8300),  D(8300),  D(0)),
    ("RB304", "Joseph Simiyu Walukanah",        D(0),     D(8300), D(0),    D(8300),  D(8300),  D(0)),
    ("RB108", "Caleb Onyango Akongo",           D(0),     D(9000), D(0),    D(9000),  D(9000),  D(0)),
    ("RB109", "Diana Ochola",                   D(207),   D(5000), D(0),    D(0),     D(5207),  D(5207)),
    ("RB110", "Jael Chebichi Bittok",           D(0),     D(9000), D(0),    D(9000),  D(9000),  D(0)),
    ("RB111", "Victor Odido Wandera",           D(18538), D(9000), D(927),  D(9000),  D(27538), D(18538)),
    ("RB201", "Beryl Alinga",                   D(0),     D(9000), D(0),    D(1000),  D(9000),  D(8000)),
    ("RB202", "Harun Ndiritu",                  D(0),     D(9000), D(0),    D(1000),  D(9000),  D(8000)),
    ("RB203", "Mariane Mukabwa",                D(-2300), D(9000), D(0),    D(6000),  D(6700),  D(700)),
    ("RB204", "Simon Murambi",                  D(0),     D(8300), D(0),    D(8200),  D(8300),  D(100)),
    ("RB205", "Shirley Tonui",                  D(7000),  D(7000), D(350),  D(14000), D(14000), D(0)),
    ("RB206", "Brian Marube Kinanga",           D(0),     D(8300), D(0),    D(8300),  D(8300),  D(0)),
    ("RB207", "Clinton Oloo Onyango",           D(5700),  D(8300), D(285),  D(5700),  D(14000), D(8300)),
    ("RB208", "Michael Kalume",                 D(-9000), D(9000), D(0),    D(0),     D(0),     D(0)),
    ("RB209", "Nassir Juma",                    D(0),     D(5000), D(0),    D(5000),  D(5000),  D(0)),
    ("RB210", "Alice Babu Boro",                D(0),     D(8300), D(0),    D(8300),  D(8300),  D(0)),
    ("RB211", "John Mboku Omega",               D(-5700), D(8300), D(0),    D(0),     D(2600),  D(2600)),
    ("RB301", "Sharon & Alex Rono",             D(2100),  D(8300), D(105),  D(8300),  D(10400), D(2100)),
    ("RB302", "Kevin Inganga",                  D(0),     D(9000), D(0),    D(9000),  D(9000),  D(0)),
    ("RB303", "Mercyline Gibson",                D(-8300), D(8300), D(0),    D(0),     D(0),     D(0)),
    ("RB107", "Boniface Mwangi",                D(-1000), D(9000), D(0),    D(9000),  D(8000),  D(-1000)),
    ("RB305", "Sheldon Mutai",                  D(1000),  D(7000), D(0),    D(7000),  D(8000),  D(1000)),
    ("RB306", "Enock Nyagoto Kombo",            D(0),     D(8300), D(0),    D(8300),  D(8300),  D(0)),
    ("RB307", "Edward Muthee",                  D(0),     D(9000), D(0),    D(9000),  D(9000),  D(0)),
    ("RB308", "Viola Tuwei",                    D(29500), D(8300), D(1475), D(0),     D(37800), D(37800)),
    ("RB309", "Harrison Njoroge Chege",         D(0),     D(5000), D(0),    D(5000),  D(5000),  D(0)),
    ("RB310", "James Wekati Ambani",            D(0),     D(9000), D(0),    D(0),     D(9000),  D(9000)),
    ("RB311", "Naom Chebet Mutai",              D(0),     D(8300), D(0),    D(8300),  D(8300),  D(0)),
    ("RB401", "Noah Omollo",                    D(0),     D(8300), D(0),    D(4000),  D(8300),  D(4300)),
    ("RB402", "Titus Odhiambo",                 D(22600), D(8300), D(1130), D(8300),  D(30900), D(22600)),
    ("RB403", "Kevin Gekonge",                  D(0),     D(9000), D(0),    D(9000),  D(9000),  D(0)),
    ("RB404", "Emmanuel Jefwa",                 D(-8300), D(8300), D(0),    D(0),     D(0),     D(0)),
    ("RB405", "Joseph Kiminja Mokare",          D(6200),  D(6300), D(310),  D(7000),  D(12500), D(5500)),
    ("RB406", "Stephen Oyugi",                  D(0),     D(9000), D(0),    D(9000),  D(9000),  D(0)),
    ("RB407", "Anthony Too",                    D(0),     D(9000), D(0),    D(0),     D(9000),  D(9000)),
    ("RB408", "Walter Amos Luzinga",            D(-700),  D(8300), D(0),    D(0),     D(7600),  D(7600)),
    ("RB409", "Titus Wanjala",                  D(0),     D(5000), D(0),    D(5000),  D(5000),  D(0)),
    ("RB410", "Dennis Charamba",                D(300),   D(8300), D(0),    D(8600),  D(8600),  D(0)),
    ("RB411", "Kipkoech Ngetich",               D(-6000), D(9000), D(0),    D(0),     D(3000),  D(3000)),
    ("RB501", "Lilian Muli",                    D(-12300),D(12300),D(0),    D(0),     D(0),     D(0)),
    ("RB001", "Wycliffe Barasa",                D(0),     D(10300),D(0),    D(10300), D(10300), D(0)),
    ("RB003", "Angela Wanyonyi",                D(0),     D(5000), D(0),    D(5000),  D(5000),  D(0)),
    ("RB005", "Faith J Kimutai",                D(28655), D(6300), D(1433), D(7050),  D(34955), D(27905)),
    ("RB006", "Boniface Kioko",                 D(0),     D(6300), D(0),    D(6300),  D(6300),  D(0)),
    ("RB008", "Andrew Mwangi",                  D(0),     D(3500), D(0),    D(3500),  D(3500),  D(0)),
    ("RB009", "Ruth Matendechere Kulundu",      D(300),   D(6500), D(0),    D(0),     D(6800),  D(6800)),
]

OTHER_CHARGES_LABEL = "Other Charges"


class Command(BaseCommand):
    help = (
        "Reconcile Wilkem Edge Apartments - Road Block, Eldoret to the 21 Aug "
        "2026 statement: fix tenant-to-unit mappings, unit rent, July opening "
        "position, August rent, other charges and payments. Dry-run unless "
        "--apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def _head(self, text):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{text}"))

    def _do(self, text):
        self.stdout.write(f"  {text}")
        self.changes += 1

    def _skip(self, text):
        self.stdout.write(self.style.WARNING(f"  skip  {text}"))

    def _note(self, text):
        self.stdout.write(self.style.NOTICE(f"  note  {text}"))

    def _ok(self, text):
        self.stdout.write(f"  ok    {text}")

    # -- entry point ----------------------------------------------------

    def handle(self, *args, **opts):
        from apps.buildings.models import Unit

        self.apply = opts["apply"]
        self.changes = 0

        building_units = Unit.objects.filter(building__name__icontains=BUILDING_NAME)
        if not building_units.exists():
            raise CommandError(f"No building matching '{BUILDING_NAME}' found.")
        self.units_by_label = {u.label.upper(): u for u in building_units}

        labels_in_statement = {label for label, *_ in STATEMENT}
        missing = labels_in_statement - set(self.units_by_label)
        if missing:
            raise CommandError(f"Units on the statement but not in the database: {sorted(missing)}")

        self._head("0a. Vacate tenants not on the statement")
        for tid, label, reason in VACATE:
            self._vacate(tid, label, reason)

        self._head("0b. Move displaced tenants to their correct unit")
        for tid, from_label, to_label in MOVES:
            self._move(tid, from_label, to_label)

        self._head("0b2. Re-let units the database has under the wrong tenant")
        for label, sitting_name, phone, kra_pin in RELET:
            self._relet(label, sitting_name, phone, kra_pin)

        self._head("0c. Create tenants missing from the database")
        for label, first, last, phone, kra_pin in NEW_TENANTS:
            self._create_tenant(label, first, last, phone, kra_pin)

        self._head("0d. Vacant units — clear status and base rent")
        for label in VACANT_UNITS:
            self._set_vacant(label)

        # Pre-flight: report which statement rows resolve to the named tenant on
        # the named unit. A row that does not resolve is skipped by every
        # financial step below — ``_step`` re-resolves before each write, so no
        # figure can land on a tenant the statement did not name — which means
        # one unresolvable row costs that row, not the property. Aborting the
        # whole run instead (what this used to do under --apply) left all 51
        # Road Block rows unreconciled because two units are let to someone the
        # statement doesn't mention.
        self._head("Pre-flight: statement rows resolve to the right tenant")
        self.unresolved = []
        for label, name, *_ in STATEMENT:
            _tenant, problem = self._resolve(label, name)
            if problem:
                self.unresolved.append(problem)
                self._skip(problem)
        if len(self.unresolved) == len(STATEMENT):
            # Nothing at all lines up: the wrong building matched, or this is
            # not the database the statement describes. Reconciling row by row
            # from there would be writing into the dark.
            raise CommandError(
                "Pre-flight failed — not one statement row resolves to its tenant. "
                "Refusing to touch financial data:\n  " + "\n  ".join(self.unresolved)
            )
        if self.unresolved and not self.apply:
            self._note(
                "(dry-run: steps 0a-0d above haven't been written yet, so a row waiting "
                "on a move or a create resolves once --apply runs)"
            )

        self._head("1. Unit base rent (August 2026 figure)")
        for label, _name, _bf, rent, *_ in STATEMENT:
            self._fix_unit_rent(label, rent)

        self._head("2. July opening position (the statement's Arrears B/F)")
        for label, name, bf, *_ in STATEMENT:
            self._step(label, name, self._reset_opening, bf)

        self._head("3. August rent (residential — no VAT)")
        for label, name, _bf, rent, *_ in STATEMENT:
            self._step(label, name, self._set_august_charge, rent)

        self._head(f"4. August {OTHER_CHARGES_LABEL.lower()}")
        for label, name, _bf, _rent, other, *_ in STATEMENT:
            self._step(label, name, self._set_other_charges, other)

        self._head("5. August payment made")
        for label, name, _bf, _rent, _other, paid, *_ in STATEMENT:
            self._step(label, name, self._record_payment, paid)

        self._head("6. Verify the rebuilt August row against the statement")
        for label, name, _bf, _rent, _other, paid, ss_total, ss_balance in STATEMENT:
            self._step(label, name, self._verify_august, paid, ss_balance, ss_total)

        if not self.apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {self.changes} change(s) would be written. Re-run with --apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nApplied {self.changes} change(s)."))

        # Printed last so it survives the couple of hundred lines above it.
        # These rows are a question for the landlord — the statement names a
        # tenant the database does not hold on that unit — not something for
        # this command to guess at.
        if self.unresolved:
            self._head(f"NOT RECONCILED — {len(self.unresolved)} row(s) need a decision")
            for problem in self.unresolved:
                self.stdout.write(self.style.WARNING(f"  {problem}"))
            self.stdout.write(
                "  Every other row was reconciled. Settle who occupies these units — "
                "correct the statement, or move the tenant — then re-run."
            )

    # -- plumbing ---------------------------------------------------------

    def _unit(self, label):
        return self.units_by_label.get(label.upper())

    def _resolve(self, label, expected_name):
        from apps.tenants.models import Tenant, TenantStatus

        unit = self._unit(label)
        if unit is None:
            return None, f"{label}: unit not found"
        tenant = Tenant.objects.filter(unit=unit, status=TenantStatus.ACTIVE).select_related("unit").first()
        if tenant is None:
            return None, f"{label}: no active tenant (expected {expected_name})"
        if tenant.full_name.strip().lower() != expected_name.strip().lower():
            return None, f"{label}: active tenant is '{tenant.full_name}', statement says '{expected_name}'"
        return tenant, None

    def _step(self, label, name, step, *args):
        tenant, problem = self._resolve(label, name)
        if problem:
            self._skip(problem)
            return
        step(tenant, label, *args)

    # -- step 0: tenant/unit realignment -----------------------------------

    def _vacate(self, tid, label, reason):
        from apps.tenants.models import Tenant, TenantStatus

        tenant = Tenant.objects.filter(pk=tid).select_related("unit").first()
        if tenant is None:
            self._skip(f"tenant #{tid}: not found — may already be resolved")
            return
        if tenant.status == TenantStatus.MOVED_OUT:
            self._skip(f"{label} {tenant.full_name}: already moved out")
            return
        if tenant.unit.label.upper() != label.upper():
            self._skip(
                f"tenant #{tid} ({tenant.full_name}) is now on {tenant.unit.label}, "
                f"not {label} — already moved, leaving alone"
            )
            return
        self._do(f"{label} {tenant.full_name}: mark moved out — {reason}")
        if self.apply:
            tenant.status = TenantStatus.MOVED_OUT
            tenant.move_out_date = AUG_POST
            tenant.move_out_notes = reason
            tenant.save(update_fields=["status", "move_out_date", "move_out_notes", "updated_at"])

    def _move(self, tid, from_label, to_label):
        from apps.tenants.models import Tenant

        tenant = Tenant.objects.filter(pk=tid).select_related("unit").first()
        if tenant is None:
            self._skip(f"tenant #{tid}: not found")
            return
        current = tenant.unit.label.upper()
        if current == to_label.upper():
            self._skip(f"{to_label} {tenant.full_name}: already on the right unit")
            return
        if current != from_label.upper():
            self._skip(
                f"tenant #{tid} ({tenant.full_name}) is on {tenant.unit.label}, "
                f"expected {from_label} — not moving, unexpected state"
            )
            return
        to_unit = self._unit(to_label)
        if to_unit is None:
            self._skip(f"{to_label}: unit not found")
            return
        self._do(f"{tenant.full_name}: move {from_label} -> {to_label}")
        if self.apply:
            tenant.unit = to_unit
            # A placeholder id_number encodes the unit it was minted for
            # (PENDING-<label>) and is unique across the table — carry it
            # over so it doesn't collide with whoever gets the old unit.
            if tenant.id_number.upper() == f"PENDING-{from_label}".upper():
                tenant.id_number = f"PENDING-{to_label.upper()}"
            tenant.save(update_fields=["unit", "id_number", "updated_at"])

    @staticmethod
    def _on_the_statement(name):
        """Does the sheet house this person, on any unit?"""
        wanted = name.strip().lower()
        return any(wanted == n.strip().lower() for _label, n, *_ in STATEMENT)

    def _relet(self, label, sitting_name, phone, kra_pin):
        """Give a unit to the tenant the statement names.

        The sitting tenant is marked moved out — never deleted, so their
        history stays on file — and the statement's tenant takes the unit.
        Guarded twice over: the unit must actually be let to the person this
        table expects, and that person must not be housed anywhere else on the
        sheet, so a re-let can never evict somebody the statement accounts for.
        """
        from apps.tenants.models import Tenant, TenantStatus

        unit = self._unit(label)
        if unit is None:
            self._skip(f"{label}: unit not found")
            return
        incoming = next(
            (n for lbl, n, *_ in STATEMENT if lbl.upper() == label.upper()), None
        )
        if incoming is None:
            self._skip(f"{label}: not on the statement")
            return

        sitting = Tenant.objects.filter(unit=unit, status=TenantStatus.ACTIVE).first()
        if sitting and sitting.full_name.strip().lower() == incoming.strip().lower():
            self._skip(f"{label}: already let to {incoming}")
            return
        if sitting and sitting.full_name.strip().lower() != sitting_name.strip().lower():
            self._skip(
                f"{label}: let to '{sitting.full_name}', this step expects "
                f"'{sitting_name}' — unexpected state, leaving alone"
            )
            return
        if sitting and self._on_the_statement(sitting.full_name):
            self._skip(
                f"{label}: '{sitting.full_name}' is housed elsewhere on the statement "
                "— not evicting them"
            )
            return

        # Who takes the unit is settled BEFORE anybody is moved out. Evicting
        # first and failing to seat a replacement would leave the unit with no
        # tenant at all — nobody to bill, and a row that reads as vacant when
        # the statement says it is let.
        mover, problem = self._seat_plan(label, unit, incoming, phone)
        if problem:
            self._skip(problem)
            return

        if sitting:
            reason = (
                f"Not on the 21 Aug 2026 Road Block statement anywhere; {label} is "
                f"let to {incoming} on it"
            )
            self._do(f"{label} {sitting.full_name}: mark moved out — {reason}")
            if self.apply:
                sitting.status = TenantStatus.MOVED_OUT
                sitting.move_out_date = AUG_POST
                sitting.move_out_notes = reason
                sitting.save(
                    update_fields=["status", "move_out_date", "move_out_notes", "updated_at"]
                )

        self._seat(label, unit, incoming, mover, phone, kra_pin)

    def _seat_plan(self, label, unit, incoming, phone):
        """Decide how ``incoming`` gets onto ``unit``, without writing anything.

        Returns ``(tenant_to_move, problem)`` — an existing record to move
        across, or ``None`` to create one, or a problem describing why neither
        is possible.

        Moving beats creating: an existing record carries the tenant's own
        Arrears history, and a duplicate would split their account in two. A
        record is only a candidate if it is not currently sitting on some other
        unit the statement accounts for — that tenant belongs where they are.
        """
        from apps.tenants.models import Tenant, TenantStatus

        first, _, last = incoming.partition(" ")
        spoken_for = {lbl.upper() for lbl, *_ in STATEMENT} - {label.upper()}
        candidates = [
            t for t in Tenant.objects.filter(
                first_name__iexact=first, last_name__iexact=last
            ).select_related("unit")
            if not (
                t.status == TenantStatus.ACTIVE
                and t.unit is not None
                and t.unit.label.upper() in spoken_for
            )
        ]

        if len(candidates) > 1:
            return None, (
                f"{label}: {len(candidates)} records named '{incoming}' — leaving for "
                "review rather than guessing which one belongs here"
            )
        if candidates:
            return candidates[0], None
        if not phone:
            # A tenant there is no way to contact is not a record worth
            # inventing, and it is not worth evicting the sitting tenant for.
            # The row stays as it is and is reported at the end of the run.
            return None, (
                f"{label}: '{incoming}' is not on file and the statement image gives "
                "no phone number — supply one to seat them"
            )
        return None, None

    def _seat(self, label, unit, incoming, mover, phone, kra_pin):
        """Carry out the plan from :meth:`_seat_plan`."""
        from apps.tenants.models import Tenant, TenantStatus

        first, _, last = incoming.partition(" ")
        rent = next(
            (r for lbl, _n, _bf, r, *_ in STATEMENT if lbl.upper() == label.upper()),
            unit.monthly_rent,
        )

        if mover is not None:
            was = mover.unit.label if mover.unit else "no unit"
            self._do(f"{label}: move {incoming} here from {was} (#{mover.pk})")
            if self.apply:
                mover.unit = unit
                mover.status = TenantStatus.ACTIVE
                mover.monthly_rent = rent
                mover.move_out_date = None
                if mover.id_number.upper().startswith("PENDING-"):
                    mover.id_number = f"PENDING-{label.upper()}"
                mover.save(update_fields=[
                    "unit", "status", "monthly_rent", "move_out_date", "id_number",
                    "updated_at",
                ])
            return

        self._do(f"{label}: create tenant {incoming} ({phone})")
        if self.apply:
            Tenant.objects.create(
                first_name=first, last_name=last,
                id_number=f"PENDING-{label.upper()}",
                kra_pin=kra_pin, phone=phone,
                unit=unit, monthly_rent=rent,
                deposit_paid=D(0),
                move_in_date=_dt.date(2026, 6, 16),
                status=TenantStatus.ACTIVE, due_day=5,
                notes=(
                    "Created from the 21 Aug 2026 Road Block statement — the unit was "
                    "on file under a tenant the statement does not name."
                ),
            )

    def _create_tenant(self, label, first, last, phone, kra_pin):
        from apps.tenants.models import Tenant, TenantStatus

        unit = self._unit(label)
        if unit is None:
            self._skip(f"{label}: unit not found")
            return
        existing = Tenant.objects.filter(
            unit=unit, first_name=first, last_name=last, status=TenantStatus.ACTIVE
        ).first()
        if existing:
            self._skip(f"{label} {first} {last}: already exists (#{existing.pk})")
            return
        rent = next((r for lbl, _n, _bf, r, *_ in STATEMENT if lbl.upper() == label.upper()), unit.monthly_rent)
        self._do(f"{label}: create tenant {first} {last} ({phone})")
        if self.apply:
            Tenant.objects.create(
                first_name=first, last_name=last,
                id_number=f"PENDING-{label.upper()}",
                kra_pin=kra_pin, phone=phone,
                unit=unit, monthly_rent=rent,
                deposit_paid=D(0),
                move_in_date=_dt.date(2026, 6, 16),
                status=TenantStatus.ACTIVE, due_day=5,
                notes="Created from the 21 Aug 2026 Road Block statement — not previously in the system.",
            )

    def _set_vacant(self, label):
        from apps.buildings.models import UnitStatus

        unit = self._unit(label)
        if unit is None:
            self._skip(f"{label}: unit not found")
            return
        if unit.status == UnitStatus.VACANT and unit.monthly_rent == 0:
            self._skip(f"{label}: already vacant at 0 rent")
            return
        self._do(f"{label}: mark vacant, base rent -> 0")
        if self.apply:
            unit.status = UnitStatus.VACANT
            unit.monthly_rent = D(0)
            unit.save(update_fields=["status", "monthly_rent", "updated_at"])

    # -- step 1: unit rent --------------------------------------------------

    def _fix_unit_rent(self, label, rent):
        unit = self._unit(label)
        if unit is None:
            self._skip(f"{label}: unit not found")
            return
        if unit.monthly_rent == rent:
            self._skip(f"{label}: base rent already {rent}")
            return
        self._do(f"{label}: base rent {unit.monthly_rent} -> {rent}")
        if self.apply:
            unit.monthly_rent = rent
            unit.save(update_fields=["monthly_rent", "updated_at"])

    # -- step 2: July opening position ---------------------------------

    def _waive_before_july(self, tenant, label, residual):
        """Write off what the roll still carries into July from before it.

        That balance no longer means anything once the statement's B/F
        supersedes it. Returns the total waived.

        ``residual`` — the rent roll's own figure — is the budget, and the
        write-off is spread newest-month-first until it is spent. Waiving each
        row's ``Arrears.balance`` instead (what this used to do) can write off
        more than the roll is carrying: the subledger allocates cash to the
        debt it settles, the roll reports it in the month it arrived, and a
        payment that FIFO pushed into another period leaves a row reading as
        unpaid that the roll has already accounted for. Sarah & Hussein
        Hamisi's June — settled in full — would have been waived a second
        time, opening July at 8,300 in credit.
        """
        from apps.payments.models import Arrears

        if residual <= 0:
            return D(0)

        earlier = list(
            Arrears.objects.filter(tenant=tenant)
            .filter(period_year__lt=JUL[0])
            .union(
                Arrears.objects.filter(
                    tenant=tenant, period_year=JUL[0], period_month__lt=JUL[1]
                )
            )
        )
        earlier.sort(key=lambda a: (a.period_year, a.period_month), reverse=True)
        if not earlier:
            return D(0)

        remaining = D(residual)
        waived = D(0)
        for arr in earlier:
            if remaining <= 0:
                break
            take = min(D(arr.balance), remaining)
            if take <= 0:
                continue
            remaining -= take
            waived += take
            self._write_off(tenant, label, arr, D(arr.waived_amount) + take, take)

        # The roll carries more than the rows can account for — a charge with no
        # Arrears row behind it, or cash the subledger allocated elsewhere. Put
        # the remainder on the newest month before July so the roll still opens
        # July flat, rather than leaving it to be papered over as a payment.
        if remaining > 0:
            arr = earlier[0]
            self._write_off(tenant, label, arr, D(arr.waived_amount) + remaining, remaining)
            waived += remaining

        return waived

    def _write_off(self, tenant, label, arr, total_waived, amount):
        self._do(
            f"{label} {tenant.full_name}: waive {amount} carried from "
            f"{arr.period_month}/{arr.period_year} (superseded by statement B/F)"
        )
        if self.apply:
            from apps.payments.models import Arrears
            from apps.payments.services import _update_arrears

            Arrears.objects.filter(pk=arr.pk).update(
                waived_amount=total_waived, waive_notes=CLEARED_NOTE
            )
            _update_arrears(tenant, arr.period_month, arr.period_year)

    def _july_position(self, tenant):
        """Where July sits on the rent roll right now.

        Returns ``(residual, other, paid, closes_at, is_opening)`` — the balance
        the roll carries INTO July from months the statement no longer speaks
        for, July's other charges, July's cash, the balance July currently
        closes on, and whether it is already marked as an opening row.

        Read off ``build_monthly_ledger`` — the same roll the dashboard and the
        statement PDF render — so the figure this step aims at is the figure the
        landlord will actually see, rather than a subledger total that can
        differ from it.
        """
        from apps.payments.models import Arrears
        from apps.payments.monthly_ledger import build_monthly_ledger

        year, month = JUL
        rows = build_monthly_ledger(tenant, months=0, today=_dt.date(year, month, 31))
        row = next(
            (r for r in rows if (r["period_year"], r["period_month"]) == (year, month)),
            None,
        )
        if row is None:
            return D(0), D(0), D(0), D(0), False

        # An opening row's charge is reported inside ``brought_forward`` rather
        # than under rent, so it has to come back out to leave the residual the
        # months before July genuinely carry.
        arr = Arrears.objects.filter(tenant=tenant, period_year=year, period_month=month).first()
        is_opening = bool(row["is_opening"])
        folded = D(arr.expected_rent) + D(arr.expected_vat) if (arr and is_opening) else D(0)
        residual = D(row["brought_forward"]) - folded
        return residual, D(row["other_charges"]), D(row["paid"]), D(row["balance"]), is_opening

    def _reset_opening(self, tenant, label, bf):
        """Rewrite July so the roll closes it on exactly the statement's B/F.

        Everything still outstanding from before July is written off first, then
        July is restated as an opening position. The figure written is NOT the
        statement's B/F itself: July in production is a genuinely billed month
        that can carry a residual in from June and can have taken cash of its
        own, while the landlord's B/F is the balance July *closes* on. So the
        opening charge is solved for --

            residual + charge + other - paid = B/F

        -- which collapses to ``charge = B/F`` on a clean account and still
        lands on the B/F when the account is not clean. Writing the B/F in
        directly (what this used to do) left July closing somewhere else
        entirely wherever June had not settled to zero or July had taken a
        payment, and August then brought that wrong figure forward.
        """
        from apps.payments.models import Arrears
        from apps.payments.services import _update_arrears

        year, month = JUL
        residual, other, paid, closes_at, is_opening = self._july_position(tenant)

        arr = Arrears.objects.filter(tenant=tenant, period_year=year, period_month=month).first()
        if (
            arr is not None
            and is_opening
            and _money(closes_at) == _money(bf)
            and arr.waived_amount == 0
            and arr.expected_vat == 0
        ):
            self._skip(f"{label} {tenant.full_name}: July already closes on {bf}")
            return

        # Written off before the opening charge is solved for, so the residual
        # the charge has to absorb is only ever what the write-off could not
        # reach. Waiving reduces the roll by exactly the amount waived, so this
        # holds in dry-run too, where nothing has been written yet.
        residual -= self._waive_before_july(tenant, label, residual)

        charge = bf - residual - other + paid
        detail = f"(residual {residual}, July other {other}, July paid {paid})"

        if charge >= 0:
            self._do(
                f"{label} {tenant.full_name}: July opening {charge} -> closes on {bf} {detail}"
            )
            if self.apply:
                with transaction.atomic():
                    self._write_opening(tenant, charge)
                    _update_arrears(tenant, month, year)
            return

        # The account carries more credit than the statement allows for, so the
        # gap is closed with cash rather than a charge — a charge here would be
        # inventing rent that was never billed.
        credit = -charge
        from apps.payments.models import Payment
        from apps.payments.services import process_payment

        key = f"RB-OPENING-CREDIT-2026-07-{label}"
        if Payment.objects.filter(tenant=tenant, idempotency_key=key).exists():
            self._skip(
                f"{label} {tenant.full_name}: July opening credit already posted, but July "
                f"closes on {closes_at} rather than {bf} — leaving for review"
            )
            return

        self._do(
            f"{label} {tenant.full_name}: July opening credit {credit} -> closes on {bf} {detail}"
        )
        if self.apply:
            with transaction.atomic():
                self._write_opening(tenant, D(0))
                process_payment(
                    tenant=tenant, amount=credit, payment_date=JULY_CLOSE,
                    period_month=month, period_year=year, source="bank",
                    reference=key, idempotency_key=key,
                    notes=(
                        "Opening credit carried from the 21 Aug 2026 Road Block "
                        "statement's Arrears B/F column."
                    ),
                )
                _update_arrears(tenant, month, year)

    def _write_opening(self, tenant, charge):
        """Create or restate July as the marked opening row."""
        from apps.payments.models import Arrears

        year, month = JUL
        arr = Arrears.objects.filter(tenant=tenant, period_year=year, period_month=month).first()
        if arr:
            Arrears.objects.filter(pk=arr.pk).update(
                expected_rent=charge, expected_vat=D(0), waived_amount=D(0),
                waive_notes=OPENING_NOTE,
            )
        else:
            Arrears.objects.create(
                tenant=tenant, period_year=year, period_month=month,
                expected_rent=charge, expected_vat=D(0), amount_paid=D(0),
                balance=charge, is_cleared=(charge == 0), waive_notes=OPENING_NOTE,
            )

    # -- step 3: August rent --------------------------------------------

    def _set_august_charge(self, tenant, label, rent):
        from apps.payments.models import Arrears
        from apps.payments.services import _update_arrears

        year, month = AUG
        arr = Arrears.objects.filter(tenant=tenant, period_year=year, period_month=month).first()
        if arr and arr.expected_rent == rent and arr.expected_vat == 0:
            self._skip(f"{label} {tenant.full_name}: August already billed {rent}")
            return
        was = f"{arr.expected_rent}" if arr else "not billed"
        self._do(f"{label} {tenant.full_name}: August {was} -> {rent}")
        if not self.apply:
            return
        with transaction.atomic():
            if arr:
                Arrears.objects.filter(pk=arr.pk).update(expected_rent=rent, expected_vat=D(0))
            else:
                Arrears.objects.create(
                    tenant=tenant, period_year=year, period_month=month,
                    expected_rent=rent, expected_vat=D(0), amount_paid=D(0),
                    balance=rent, is_cleared=False,
                )
            _update_arrears(tenant, month, year)

    # -- step 4: other charges -------------------------------------------

    def _set_other_charges(self, tenant, label, amount):
        from apps.payments.models import UtilityCharge

        year, month = AUG
        existing = UtilityCharge.objects.filter(tenant=tenant, period_year=year, period_month=month)
        current = sum((u.amount for u in existing), D(0))
        if current == amount:
            self._skip(f"{label} {tenant.full_name}: " + (f"already {amount}" if amount else "no other charges"))
            return
        if existing.exists():
            self._skip(
                f"{label} {tenant.full_name}: has {current} of other charges but statement "
                f"says {amount} — leaving for review rather than overwriting"
            )
            return
        if amount == 0:
            self._skip(f"{label} {tenant.full_name}: no other charges")
            return
        self._do(f"{label} {tenant.full_name}: August other charges {amount}")
        if self.apply:
            UtilityCharge.objects.create(
                tenant=tenant, posting_date=AUG_POST, period_year=year, period_month=month,
                label=OTHER_CHARGES_LABEL, amount=amount,
                notes="From the 21 Aug 2026 Road Block statement's 'Others Charges' column.",
            )

    # -- step 5: payment made ------------------------------------------

    def _record_payment(self, tenant, label, amount):
        """Bring August cash up to the statement's 'Payment made' figure.

        Only the shortfall is posted. Production already holds real August
        receipts — the Co-op feed keeps banking them — so posting the
        statement figure outright doubled the month for every tenant who had
        actually paid: Sarah & Hussein Hamisi's 8,300 would have gone in
        beside the 8,300 already on the account.

        Cash banked ABOVE the statement figure is never removed. A receipt is
        real money and not the statement's to delete, so the difference is
        reported for review instead.
        """
        from django.db.models import Sum

        from apps.payments.models import Payment, PaymentType
        from apps.payments.services import process_payment

        year, month = AUG
        target = _money(amount)
        # Deposits are a refundable liability, not rent — the same exclusion the
        # rent roll and the statement make, so the three figures agree.
        banked = _money(
            Payment.objects.filter(
                tenant=tenant, voided_at__isnull=True,
                payment_date__year=year, payment_date__month=month,
            ).exclude(payment_type=PaymentType.DEPOSIT).aggregate(t=Sum("amount"))["t"] or 0
        )

        if banked == target:
            self._skip(
                f"{label} {tenant.full_name}: August cash already {target}"
                if target else f"{label} {tenant.full_name}: no payment on the statement"
            )
            return
        if banked > target:
            self._note(
                f"{label} {tenant.full_name}: {banked} of August cash on the account but the "
                f"statement says {target} — extra {banked - target} left alone for review"
            )
            return

        shortfall = target - banked
        key = self._free_key(tenant, f"RB-AUG-2026-{label}")
        self._do(
            f"{label} {tenant.full_name}: August cash {banked} -> {target} (post {shortfall})"
        )
        if self.apply:
            process_payment(
                tenant=tenant, amount=shortfall, payment_date=AUG_PAY,
                period_month=month, period_year=year, source="bank",
                reference=key, idempotency_key=key,
                notes="From the 21 Aug 2026 Road Block statement's 'Payment made' column.",
            )

    @staticmethod
    def _free_key(tenant, base):
        """``base``, or the first ``base-2``, ``base-3``… not yet used.

        ``idempotency_key`` is unique per tenant, so a second top-up against a
        month that was already partly seeded needs a key of its own.
        """
        from apps.payments.models import Payment

        keys = set(
            Payment.objects.filter(tenant=tenant, idempotency_key__startswith=base)
            .values_list("idempotency_key", flat=True)
        )
        if base not in keys:
            return base
        n = 2
        while f"{base}-{n}" in keys:
            n += 1
        return f"{base}-{n}"

    # -- step 6: verify ----------------------------------------------------

    def _verify_august(self, tenant, label, ss_paid, ss_balance, ss_total):
        from apps.payments.monthly_ledger import build_monthly_ledger

        year, month = AUG
        computed_total = None
        for label2, _n, bf, rent, other, *_ in STATEMENT:
            if label2 == label:
                computed_total = bf + rent + other
                break
        if computed_total is not None and _money(computed_total) != _money(ss_total):
            self._note(
                f"{label} {tenant.full_name}: statement's own 'Rent + Arrears' total "
                f"({ss_total}) doesn't equal its own Aug rent + B/F + other "
                f"({_money(computed_total)}) — spreadsheet arithmetic, not a system issue"
            )

        if not self.apply:
            self._note(f"{label} {tenant.full_name}: balance checked after --apply")
            return

        row = next(
            (
                r for r in build_monthly_ledger(tenant, months=0, today=_dt.date(year, month, 21))
                if (r["period_year"], r["period_month"]) == (year, month)
            ),
            None,
        )
        if row is None:
            self._skip(f"{label} {tenant.full_name}: no August row to check")
            return

        got_paid, got_balance = _money(row["paid"]), _money(row["balance"])
        if got_paid == _money(ss_paid) and got_balance == _money(ss_balance):
            self._ok(f"{label} {tenant.full_name}: paid {got_paid}, balance {got_balance}")
            return

        detail = []
        if got_paid != _money(ss_paid):
            detail.append(f"paid {got_paid} vs statement {ss_paid}")
        if got_balance != _money(ss_balance):
            detail.append(f"balance {got_balance} vs statement {ss_balance}")
        self._note(
            f"{label} {tenant.full_name}: {'; '.join(detail)} "
            f"(b/f {row['brought_forward']} + rent {row['rent']} + other "
            f"{row['other_charges']} - paid {row['paid']} = {row['balance']})"
        )
