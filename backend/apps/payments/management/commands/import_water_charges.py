"""
Import monthly water-consumption charges from the Wilkem Edge water sheet.

The sheet ("Monthly Water Consumption - Wilkem Edge Apartments, Donholm Estate")
lists one 3-row block per unit:

    <UNIT CODE> | <TENANT NAME> | CLOSING RDG    | jan | feb | mar | ...
                                | UNITS CONSUMED | ...
                                | VALUE (KSHS)   | ...

Month columns are headed by an Excel date-serial (first of each month). Each
(unit, month) cell trio becomes one ``UtilityCharge`` row (label "Water Usage")
against the unit's active tenant, so water then flows onto the rent statement
ledger and into the receipt "Other Charges" total.

Common-area rows ("COMMON SERVICES" / "COMMON USAGE") are landlord consumption,
not billable to a tenant, and are skipped.

Usage:
    python manage.py import_water_charges "path/to/water.xlsx"
    python manage.py import_water_charges "path/to/water.xlsx" --dry-run

Re-running is safe: an existing Water Usage charge for the same tenant + period
is updated in place (idempotent), never duplicated.
"""
import calendar
import datetime as dt
import re
import zipfile
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_EXCEL_EPOCH = dt.date(1899, 12, 30)  # Excel's day-0 (accounts for the 1900 leap bug)
WATER_LABEL = "Water Usage"


def _num(raw):
    """Parse a numeric cell to Decimal, or None if blank / non-numeric (e.g. #REF!)."""
    s = str(raw or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _read_sheet(path):
    """Return {row_number: {col_letter: value}} for the first worksheet.

    Uses only the stdlib so the importer carries no extra runtime dependency.
    """
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CommandError(f"Could not open {path!r} as an .xlsx file: {exc}") from exc

    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))

    rows = {}
    for c in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{_NS}c"):
        ref, ctype = c.get("r"), c.get("t")
        v, inline = c.find(f"{_NS}v"), c.find(f"{_NS}is")
        if ctype == "s" and v is not None:
            val = shared[int(v.text)]
        elif inline is not None:
            val = "".join(t.text or "" for t in inline.iter(f"{_NS}t"))
        elif v is not None:
            val = v.text
        else:
            val = None
        m = re.match(r"([A-Z]+)(\d+)", ref)
        rows.setdefault(int(m.group(2)), {})[m.group(1)] = val
    return rows


def _serial_to_year_month(serial):
    d = _EXCEL_EPOCH + dt.timedelta(days=int(float(serial)))
    return d.year, d.month


class Command(BaseCommand):
    help = "Import monthly water-consumption charges from the Wilkem water .xlsx sheet."

    def add_arguments(self, parser):
        parser.add_argument("xlsx_path", help="Path to the water-consumption .xlsx file.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Parse and report only; roll back all writes.",
        )
        parser.add_argument(
            "--label", default=WATER_LABEL,
            help=f"Charge label to post (default: {WATER_LABEL!r}).",
        )

    def handle(self, *args, **opts):
        from apps.buildings.models import Unit
        from apps.payments.models import UtilityCharge

        rows = _read_sheet(opts["xlsx_path"])
        label = opts["label"]

        # --- locate the header row (col A == "UNIT") and the month columns -----
        header_row = next(
            (rn for rn in sorted(rows) if str(rows[rn].get("A") or "").strip().upper() == "UNIT"),
            None,
        )
        if header_row is None:
            raise CommandError("Could not find the header row (a row with 'UNIT' in column A).")

        months = {}  # col_letter -> (year, month)
        for col, raw in rows[header_row].items():
            if col in ("A", "B", "C", "D"):
                continue
            if raw and str(raw).replace(".", "").isdigit():
                months[col] = _serial_to_year_month(raw)
        if not months:
            raise CommandError("No month columns (date-serials) found on the header row.")
        self.stdout.write(
            "Month columns: "
            + ", ".join(f"{c}={y}-{m:02d}" for c, (y, m) in sorted(months.items()))
        )

        # --- group the sheet into per-unit blocks ------------------------------
        blocks, current = [], None
        for rn in sorted(rows):
            if rn <= header_row:
                continue
            row = rows[rn]
            code = str(row.get("A") or "").strip()
            ckind = str(row.get("C") or "").strip().upper()
            if code:  # start of a new block
                current = {"code": code, "tenant_name": str(row.get("B") or "").strip(), "lines": {}}
                blocks.append(current)
            if current is None:
                continue
            if "CLOSING" in ckind:
                current["lines"]["closing"] = row
            elif "CONSUM" in ckind:  # "UNITS CONSUMED" / "CONSUMPTION"
                current["lines"]["units"] = row
            elif "VALUE" in ckind:
                current["lines"]["value"] = row

        created = updated = skipped_cells = 0
        unmatched, per_unit = [], []

        with transaction.atomic():
            for blk in blocks:
                code = blk["code"]
                if code.upper().startswith("COMMON"):
                    continue  # landlord common-area water, not billed to a tenant

                unit = Unit.objects.filter(label__iexact=code).select_related("building").first()
                if unit is None:
                    unmatched.append(f"{code} (no matching unit)")
                    continue
                tenant = unit.tenants.filter(status__in=["active", "notice_given"]).first()
                if tenant is None:
                    unmatched.append(f"{code} (no active tenant)")
                    continue

                closing = blk["lines"].get("closing", {})
                units = blk["lines"].get("units", {})
                value = blk["lines"].get("value", {})

                n_for_unit = 0
                prev_closing = None
                for col in sorted(months, key=lambda c: months[c]):
                    year, month = months[col]
                    amount = _num(value.get(col))
                    consumed = _num(units.get(col))
                    close_rdg = _num(closing.get(col))

                    # Opening reading = last month's closing (falls back to
                    # closing - consumed for the earliest month on the sheet).
                    if prev_closing is not None:
                        opening = prev_closing
                    elif close_rdg is not None and consumed is not None:
                        opening = close_rdg - consumed
                    else:
                        opening = None
                    prev_closing = close_rdg if close_rdg is not None else prev_closing

                    if amount is None or amount <= 0:
                        skipped_cells += 1
                        continue

                    posting_date = dt.date(year, month, calendar.monthrange(year, month)[1])
                    _, was_created = UtilityCharge.objects.update_or_create(
                        tenant=tenant, period_month=month, period_year=year, label=label,
                        defaults={
                            "posting_date": posting_date,
                            "units": consumed,
                            "opening_reading": opening,
                            "closing_reading": close_rdg,
                            "amount": amount.quantize(Decimal("0.01")),
                        },
                    )
                    created += was_created
                    updated += not was_created
                    n_for_unit += 1
                per_unit.append(f"{code} -> {tenant.full_name}: {n_for_unit} month(s)")

            if opts["dry_run"]:
                transaction.set_rollback(True)

        # --- report ------------------------------------------------------------
        self.stdout.write("")
        for line in per_unit:
            self.stdout.write("  " + line)
        if unmatched:
            self.stdout.write(self.style.WARNING("\nUnmatched / skipped units:"))
            for u in unmatched:
                self.stdout.write(self.style.WARNING("  " + u))
        summary = (
            f"\n{created} created, {updated} updated, "
            f"{skipped_cells} empty cell(s) skipped, {len(unmatched)} unit(s) unmatched."
        )
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING(summary + "  [DRY RUN — rolled back]"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
