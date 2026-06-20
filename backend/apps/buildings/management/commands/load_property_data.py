"""
Load the real property portfolio (buildings, units, tenants + opening balances)
from a CSV exported from the rent roll.

Why CSV (not hard-coded): the rent roll is real money + contact data — phone
numbers drive payment matching and balances are real arrears. Importing the
spreadsheet directly (one row per unit) avoids hand-transcription errors.

Expected CSV columns (header row, exact names; order doesn't matter):

    property_code, property_name, location, classification, unit_code,
    unit_type, monthly_rent, tenant_name, kra_pin, id_number, phone,
    deposit, opening_balance, move_in_date

  - Leave tenant_name blank for a vacant unit (unit is created, no tenant).
  - classification: "business"/"commercial" → commercial income (4120); else residential.
  - opening_balance: net owed as at the cutover. Negative = tenant in credit.
  - move_in_date / id_number / kra_pin: optional (sensible fallbacks applied).

Usage:
    python manage.py load_property_data roll.csv --reset --as-of 2026-06-16
    python manage.py load_property_data roll.csv --dry-run        # parse + report, no writes

Safety:
  --reset wipes existing buildings/units/tenants FIRST (to honour "only the real
  portfolio should exist"), but REFUSES if any real Payment exists unless --force,
  so it can never silently destroy recorded money. --dry-run rolls everything back.
"""
import csv
import datetime as dt
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

KRA_RE = re.compile(r"^[AP]\d{9}[A-Z]$")
REQUIRED_COLUMNS = {
    "property_code", "property_name", "unit_code", "monthly_rent",
    "tenant_name", "phone", "deposit", "opening_balance",
}


def _money(raw) -> Decimal:
    s = str(raw or "").strip().replace(",", "").replace("KES", "").strip()
    if s in ("", "-", "—"):
        return Decimal("0")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0")


def _normalize_phone(phone: str) -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    return "+" + digits


def _split_name(raw: str):
    """('Wycliffe Barasa - Bakery') -> ('Wycliffe', 'Barasa', 'Bakery' note)."""
    name = (raw or "").strip()
    suffix = ""
    if " - " in name:
        name, suffix = (p.strip() for p in name.split(" - ", 1))
    parts = name.split()
    if not parts:
        return "", "", suffix
    first = parts[0]
    last = " ".join(parts[1:]) or first
    return first, last, suffix


class Command(BaseCommand):
    help = "Load buildings/units/tenants + opening balances from a rent-roll CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--reset", action="store_true",
                            help="Delete existing buildings/units/tenants before loading.")
        parser.add_argument("--force", action="store_true",
                            help="Allow --reset even if real Payments exist (DANGEROUS).")
        parser.add_argument("--as-of", default="2026-06-16",
                            help="Cutover date for opening balances (YYYY-MM-DD).")
        parser.add_argument("--no-opening-balances", action="store_true",
                            help="Load master data only; skip Arrears + ledger postings.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse, validate and report, then roll back (no writes).")

    def handle(self, *args, **opts):
        from apps.buildings.models import Building, Unit, UnitClassification
        from apps.payments.models import Arrears, Payment
        from apps.tenants.models import Tenant, TenantStatus

        try:
            as_of = dt.date.fromisoformat(opts["as_of"])
        except ValueError:
            raise CommandError(f"--as-of must be YYYY-MM-DD, got {opts['as_of']!r}") from None

        rows = self._read_csv(opts["csv_path"])
        self.stdout.write(f"Parsed {len(rows)} unit row(s) from {opts['csv_path']}.")

        issues: list[str] = []

        try:
            with transaction.atomic():
                if opts["reset"]:
                    self._reset(Building, Unit, Tenant, Arrears, Payment, opts["force"])

                buildings: dict[str, object] = {}
                per_property = defaultdict(lambda: {"units": 0, "tenants": 0,
                                                     "rent": Decimal("0"),
                                                     "deposit": Decimal("0"),
                                                     "opening": Decimal("0")})

                for i, row in enumerate(rows, start=2):  # row 1 is the header
                    code = (row["property_code"] or "").strip().upper()
                    if not code:
                        issues.append(f"row {i}: blank property_code — skipped")
                        continue

                    building = buildings.get(code)
                    if building is None:
                        building, _ = Building.objects.update_or_create(
                            code=code,
                            defaults={
                                "name": (row.get("property_name") or code).strip(),
                                "address": (row.get("location") or "").strip(),
                            },
                        )
                        buildings[code] = building

                    label = (row["unit_code"] or "").strip()
                    if not label:
                        issues.append(f"row {i}: blank unit_code — skipped")
                        continue

                    classification = (
                        UnitClassification.BUSINESS
                        if (row.get("classification") or "").strip().lower()
                        in ("business", "commercial", "com")
                        else UnitClassification.RESIDENTIAL
                    )
                    rent = _money(row["monthly_rent"])
                    unit, _ = Unit.objects.update_or_create(
                        label=label,
                        defaults={
                            "building": building,
                            "monthly_rent": rent,
                            "classification": classification,
                            "unit_type": (row.get("unit_type") or "single").strip() or "single",
                        },
                    )

                    stats = per_property[code]
                    stats["units"] += 1
                    stats["rent"] += rent

                    name = (row.get("tenant_name") or "").strip()
                    if not name or name.lower() in ("vacant", "vacant.", "-"):
                        continue  # vacant unit, no tenant

                    first, last, suffix = _split_name(name)
                    raw_pin = (row.get("kra_pin") or "").strip().upper()
                    kra_pin, pin_note = ("", "")
                    if KRA_RE.match(raw_pin):
                        kra_pin = raw_pin
                    elif raw_pin:
                        pin_note = f"KRA/ID on file: {raw_pin}"
                        issues.append(f"row {i} ({label}): KRA PIN {raw_pin!r} not valid format - stored in notes")

                    id_number = (row.get("id_number") or "").strip() or f"PENDING-{label}"
                    phone = _normalize_phone(row.get("phone"))
                    if not phone:
                        issues.append(f"row {i} ({label}): no phone — payment phone-fallback won't work")
                    deposit = _money(row.get("deposit"))
                    opening = _money(row.get("opening_balance"))
                    move_in = (row.get("move_in_date") or "").strip()
                    try:
                        move_in_date = dt.date.fromisoformat(move_in) if move_in else as_of
                    except ValueError:
                        move_in_date = as_of
                        issues.append(f"row {i} ({label}): bad move_in_date {move_in!r} — defaulted to {as_of}")

                    note_bits = [b for b in (suffix and f"Type: {suffix}", pin_note) if b]
                    tenant, _ = Tenant.objects.update_or_create(
                        unit=unit,
                        defaults={
                            "first_name": first, "last_name": last,
                            "id_number": id_number, "kra_pin": kra_pin,
                            "phone": phone, "monthly_rent": rent,
                            "deposit_paid": deposit, "move_in_date": move_in_date,
                            "status": TenantStatus.ACTIVE,
                            "notes": "; ".join(note_bits),
                        },
                    )
                    stats["tenants"] += 1
                    stats["deposit"] += deposit
                    stats["opening"] += opening

                    if not opts["no_opening_balances"]:
                        Arrears.objects.update_or_create(
                            tenant=tenant,
                            period_month=as_of.month, period_year=as_of.year,
                            defaults={
                                "expected_rent": opening if opening > 0 else Decimal("0"),
                                "amount_paid": Decimal("0"),
                                "balance": opening,
                                "is_cleared": opening <= 0,
                            },
                        )
                        from apps.ledger.posting import post_opening_balances
                        post_opening_balances(
                            tenant, net_balance=opening, deposit=deposit, date=as_of,
                        )

                self._report(per_property, issues)

                if opts["dry_run"]:
                    self.stdout.write(self.style.WARNING("\n--dry-run: rolling back, nothing written."))
                    transaction.set_rollback(True)
        except Exception as exc:
            raise CommandError(f"Load failed (rolled back): {exc}") from exc

        if not opts["dry_run"]:
            self.stdout.write(self.style.SUCCESS("\nLoad committed."))

    # ── helpers ───────────────────────────────────────────────────────────

    def _read_csv(self, path):
        try:
            with open(path, newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
                if missing:
                    raise CommandError(f"CSV missing columns: {', '.join(sorted(missing))}")
                return [r for r in reader if any((v or "").strip() for v in r.values())]
        except FileNotFoundError:
            raise CommandError(f"CSV not found: {path}") from None

    def _reset(self, Building, Unit, Tenant, Arrears, Payment, force):
        payment_count = Payment.objects.count()
        if payment_count and not force:
            raise CommandError(
                f"Refusing --reset: {payment_count} Payment row(s) exist (real money). "
                f"Re-run with --force only if you are certain this is demo data."
            )
        self.stdout.write(self.style.WARNING(
            f"--reset: clearing {Building.objects.count()} building(s), "
            f"{Unit.objects.count()} unit(s), {Tenant.objects.count()} tenant(s)..."
        ))
        # Tenant.unit is PROTECT, so tenants (and their dependents) go before units.
        Arrears.objects.all().delete()
        Payment.objects.all().delete()
        Tenant.objects.all().delete()
        Unit.objects.all().delete()
        Building.objects.all().delete()

    def _report(self, per_property, issues):
        self.stdout.write("\n-- Reconciliation (verify against the rent roll) --")
        tot = defaultdict(Decimal)
        for code in sorted(per_property):
            s = per_property[code]
            self.stdout.write(
                f"  {code:6} units={s['units']:>3}  tenants={s['tenants']:>3}  "
                f"rent={s['rent']:>12,.2f}  deposits={s['deposit']:>12,.2f}  "
                f"opening_bal={s['opening']:>12,.2f}"
            )
            for k in ("units", "tenants", "rent", "deposit", "opening"):
                tot[k] += s[k]
        self.stdout.write(
            f"  {'TOTAL':6} units={tot['units']:>3}  tenants={tot['tenants']:>3}  "
            f"rent={tot['rent']:>12,.2f}  deposits={tot['deposit']:>12,.2f}  "
            f"opening_bal={tot['opening']:>12,.2f}"
        )
        if issues:
            self.stdout.write(self.style.WARNING(f"\n-- {len(issues)} data note(s) --"))
            for msg in issues:
                self.stdout.write(f"  - {msg}")
