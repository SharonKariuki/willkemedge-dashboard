"""
Onboard the Wilkem Edge Business Arcade (Matasia) from its rent-roll .xlsx.

The workbook has two sheets — "Commercial Tenants" and "Residential Tenants" —
that share one rent-roll layout (one row per unit). This command reads them
with a stdlib-only .xlsx parser, maps each row to the CSV schema that the
existing, tested ``load_property_data`` command expects, and delegates the
actual create/update + opening-balance ledger posting to it. That keeps a
single onboarding code path for every property.

Decisions baked in (confirmed with the owner):
  * Commercial rent ("Reserved Rent + S/Charge") is VAT-EXCLUSIVE — stored
    as-is; the statement engine adds 16% VAT for BUSINESS units.
  * Opening balance = column T ("Total Unpaid Balance"), the net owed at cutover.
  * Commercial sheet -> BUSINESS units (16% VAT); Residential -> RESIDENTIAL.

Usage:
    python manage.py import_matasia "path/to/Matasia.xlsx" --dry-run
    python manage.py import_matasia "path/to/Matasia.xlsx"            # real load

This is ADDITIVE (never --reset): it augments the existing portfolio.
"""
import csv
import datetime as dt
import os
import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_EXCEL_EPOCH = dt.date(1899, 12, 30)

PROPERTY_CODE = "MAT"
PROPERTY_NAME = "Wilkem Edge Business Arcade - Matasia"
PROPERTY_LOCATION = "Matasia, Ngong"

# The two sheets have DIFFERENT layouts (row 5 header, data from row 6).
#
# Residential — B unit · C tenant · D phone · E KRA · F ID · H rent (no VAT) ·
#               T total unpaid balance.
# Commercial  — B old-unit · C NEW code · D tenant · E contact · F phone ·
#               G KRA · H gross rent · J base rent · K 16% VAT · Q unpaid balance.
#               Base rent (J) is stored so the BUSINESS engine re-adds 16% VAT.
COLS_RESIDENTIAL = {
    "unit": "B", "tenant": "C", "phone": "D", "kra": "E", "id": "F",
    "rent": "H", "unpaid_balance": "T", "vat": None, "gross_rent": None,
}
COLS_COMMERCIAL = {
    "unit": "C", "unit_fallback": "B", "tenant": "D", "phone": "F", "kra": "G",
    "id": None, "rent": "J", "gross_rent": "H", "vat": "K", "unpaid_balance": "Q",
}


def _strip_prefix(value):
    """Drop 'PIN:' / 'Tel:' label prefixes the sheet embeds in cells."""
    s = str(value or "").strip()
    s = re.sub(r"^(PIN|Tel)\s*:\s*", "", s, flags=re.IGNORECASE)
    return s.strip()

CSV_COLUMNS = [
    "property_code", "property_name", "location", "classification",
    "unit_code", "unit_type", "monthly_rent", "tenant_name", "kra_pin",
    "id_number", "phone", "deposit", "opening_balance", "move_in_date",
]


def _sheets(path):
    """Yield (sheet_name, {row: {col: value}}) for every worksheet, in order."""
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CommandError(f"Could not open {path!r} as an .xlsx file: {exc}") from exc

    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))

    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {r.get("Id"): r.get("Target") for r in rels}
    wb = ET.fromstring(z.read("xl/workbook.xml"))

    for sheet in wb.iter(f"{_NS}sheet"):
        target = relmap[sheet.get(_RID)]
        member = "xl/" + target.lstrip("/")
        rows = {}
        for c in ET.fromstring(z.read(member)).iter(f"{_NS}c"):
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
        yield sheet.get("name"), rows


def _clean(value):
    """Blank out sheet placeholders. Contact/identity cells use '0' to mean
    'none on file'; treat that as empty so load_property_data can assign a
    unique PENDING id rather than colliding many tenants on id_number '0'."""
    s = str(value or "").strip()
    return "" if s in ("", "0") else s


def _as_of_from(rows):
    """Read the 'RENT STATEMENT AS ON' date-serial (cell N3) if present."""
    serial = (rows.get(3, {}) or {}).get("N")
    if serial and str(serial).replace(".", "").isdigit():
        return _EXCEL_EPOCH + dt.timedelta(days=int(float(serial)))
    return None


class Command(BaseCommand):
    help = "Onboard the Matasia Business Arcade from its rent-roll .xlsx (delegates to load_property_data)."

    def add_arguments(self, parser):
        parser.add_argument("xlsx_path")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse, convert and report, then roll back (no writes).")
        parser.add_argument("--as-of", default=None,
                            help="Cutover date for opening balances (YYYY-MM-DD). "
                                 "Defaults to the sheet's statement date.")

    def handle(self, *args, **opts):
        sheets = list(_sheets(opts["xlsx_path"]))
        if not sheets:
            raise CommandError("No worksheets found in the workbook.")

        as_of = opts["as_of"] or (_as_of_from(sheets[0][1]) or dt.date(2026, 6, 30)).isoformat()

        out_rows, occupied = [], 0
        vat_exempt = []  # commercial units the sheet shows with 0 VAT
        for name, rows in sheets:
            is_commercial = "commercial" in name.lower()
            cols = COLS_COMMERCIAL if is_commercial else COLS_RESIDENTIAL
            classification = "commercial" if is_commercial else "residential"
            unit_type = "shop" if is_commercial else "single"
            n_units = n_occ = 0
            for rn in sorted(rows):
                if rn <= 5:
                    continue
                row = rows[rn]
                unit_code = str(row.get(cols["unit"]) or "").strip()
                if not unit_code and cols.get("unit_fallback"):
                    unit_code = str(row.get(cols["unit_fallback"]) or "").strip()
                if not unit_code:
                    continue
                tenant = str(row.get(cols["tenant"]) or "").strip()
                n_units += 1
                if tenant and tenant.lower() != "vacant":
                    n_occ += 1
                    if is_commercial and (_clean(row.get(cols["vat"])) in (None, "")):
                        vat_exempt.append(unit_code)
                out_rows.append({
                    "property_code": PROPERTY_CODE,
                    "property_name": PROPERTY_NAME,
                    "location": PROPERTY_LOCATION,
                    "classification": classification,
                    "unit_code": unit_code,
                    "unit_type": unit_type,
                    # Commercial stores BASE rent (J); the engine adds 16% VAT.
                    "monthly_rent": row.get(cols["rent"]) or "0",
                    "tenant_name": tenant,
                    "kra_pin": _clean(_strip_prefix(row.get(cols["kra"]))),
                    "id_number": _clean(row.get(cols["id"])) if cols.get("id") else "",
                    "phone": _clean(_strip_prefix(row.get(cols["phone"]))),
                    "deposit": "0",  # not tracked on this sheet
                    "opening_balance": row.get(cols["unpaid_balance"]) or "0",
                    "move_in_date": "",  # defaults to --as-of in load_property_data
                })
            occupied += n_occ
            self.stdout.write(f"{name}: {n_units} unit(s), {n_occ} occupied ({classification}).")

        if vat_exempt:
            self.stdout.write(self.style.WARNING(
                f"\n[REVIEW] {len(vat_exempt)} commercial unit(s) show 0 VAT on the "
                f"sheet but will get 16% added under BUSINESS classification: "
                f"{', '.join(vat_exempt)}.\n  Confirm with the owner before the real load."
            ))

        self.stdout.write(
            f"\nPrepared {len(out_rows)} unit row(s), {occupied} occupied. "
            f"Cutover (--as-of) = {as_of}. Delegating to load_property_data...\n"
        )

        # Write the converted rows to a short-lived CSV and reuse the tested
        # onboarding command. The temp file is always removed afterwards.
        fd, tmp_name = tempfile.mkstemp(prefix="matasia_", suffix=".csv")
        os.close(fd)  # close the OS handle so Windows can unlink it later
        tmp = Path(tmp_name)
        try:
            with tmp.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(out_rows)
            call_command(
                "load_property_data", str(tmp),
                as_of=as_of, dry_run=opts["dry_run"],
            )
        finally:
            tmp.unlink(missing_ok=True)
