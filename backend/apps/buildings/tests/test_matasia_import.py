"""
Tests for the import_matasia management command (Day 6 · Matasia onboarding).

Builds a synthetic two-sheet workbook (Commercial + Residential, with the two
different layouts) and asserts the command creates the building, units,
tenants, and opening-balance arrears correctly — and that commercial units get
BUSINESS classification with the base rent stored (VAT re-added by the engine).
"""
import io
import zipfile
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitClassification
from apps.tenants.models import Tenant

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _sheet_xml(rows):
    def cell(col, rn, val):
        ref = f"{col}{rn}"
        if isinstance(val, str):
            return f'<c r="{ref}" t="inlineStr"><is><t>{val}</t></is></c>'
        return f'<c r="{ref}"><v>{val}</v></c>'
    body = "".join(
        f'<row r="{rn}">{"".join(cell(c, rn, v) for c, v in rows[rn].items())}</row>'
        for rn in sorted(rows)
    )
    return f'<?xml version="1.0"?><worksheet xmlns="{MAIN}"><sheetData>{body}</sheetData></worksheet>'


def _make_workbook(sheets):
    """sheets = [(name, {row: {col: value}}), ...] -> .xlsx bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        sheet_tags, rel_tags = [], []
        for i, (name, rows) in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows))
            sheet_tags.append(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>')
            rel_tags.append(
                f'<Relationship Id="rId{i}" Type="{RELS}/worksheet" '
                f'Target="worksheets/sheet{i}.xml"/>'
            )
        z.writestr(
            "xl/workbook.xml",
            f'<?xml version="1.0"?><workbook xmlns="{MAIN}" xmlns:r="{RELS}">'
            f'<sheets>{"".join(sheet_tags)}</sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<?xml version="1.0"?><Relationships xmlns="{PKG_RELS}">{"".join(rel_tags)}</Relationships>',
        )
    return buf.getvalue()


@pytest.fixture
def matasia_file(tmp_path):
    commercial = {
        5: {"B": "UNIT NUMBER", "C": "NEW UNIT NUMBER", "D": "TENANT NAME"},
        # occupied: base rent 24000 (+16% VAT 3840), unpaid balance 12000
        6: {"C": "MCG01", "D": "Biz Ltd", "F": "Tel: 0722000000",
            "G": "PIN: P052438828Z", "H": 27840, "J": 24000, "K": 3840, "Q": 12000},
        # vacant commercial unit
        7: {"C": "MCG02", "D": "Vacant", "J": 20000, "K": 0, "Q": 0},
    }
    residential = {
        5: {"B": "UNIT NUMBER", "C": "TENANT NAME"},
        6: {"B": "MR201", "C": "Jane Doe", "D": "0711000000",
            "E": "A012345678B", "F": "12345678", "H": 20000, "T": 3000},
        7: {"B": "MR202", "C": "Vacant", "H": 18000, "T": 0},
    }
    path = tmp_path / "matasia.xlsx"
    path.write_bytes(_make_workbook([("Commercial Tenants", commercial),
                                     ("Residential Tenants", residential)]))
    return str(path)


@pytest.mark.django_db
class TestImportMatasia:
    def test_creates_building_and_units(self, matasia_file):
        call_command("import_matasia", matasia_file, as_of="2026-06-30")
        building = Building.objects.get(code="MAT")
        assert building.units.count() == 4  # 2 commercial + 2 residential

    def test_commercial_unit_is_business_with_base_rent(self, matasia_file):
        call_command("import_matasia", matasia_file, as_of="2026-06-30")
        u = Unit.objects.get(label="MCG01")
        assert u.classification == UnitClassification.BUSINESS
        # Base rent stored (the engine adds 16% VAT on top).
        assert u.monthly_rent == Decimal("24000.00")

    def test_residential_unit_is_residential(self, matasia_file):
        call_command("import_matasia", matasia_file, as_of="2026-06-30")
        u = Unit.objects.get(label="MR201")
        assert u.classification == UnitClassification.RESIDENTIAL
        assert u.monthly_rent == Decimal("20000.00")

    def test_opening_balance_becomes_arrears(self, matasia_file):
        call_command("import_matasia", matasia_file, as_of="2026-06-30")
        tenant = Tenant.objects.get(unit__label="MCG01")
        arr = tenant.arrears.get(period_month=6, period_year=2026)
        assert arr.balance == Decimal("12000.00")

    def test_vacant_units_have_no_tenant(self, matasia_file):
        call_command("import_matasia", matasia_file, as_of="2026-06-30")
        assert not Tenant.objects.filter(unit__label="MCG02").exists()
        assert not Tenant.objects.filter(unit__label="MR202").exists()

    def test_dry_run_writes_nothing(self, matasia_file):
        call_command("import_matasia", matasia_file, "--dry-run", as_of="2026-06-30")
        assert not Building.objects.filter(code="MAT").exists()
