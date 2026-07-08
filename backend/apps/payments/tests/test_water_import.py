"""
Tests for the import_water_charges management command (Day 6 · water billing).

Builds a minimal in-memory .xlsx (inline strings + numbers) that mirrors the
real sheet's shape — a header row of month date-serials, per-unit 3-row blocks,
and a COMMON SERVICES block that must be skipped.
"""
import io
import zipfile
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import UtilityCharge
from apps.tenants.models import Tenant, TenantStatus

# Excel date-serials for the first of Jan/Feb 2026.
JAN_2026, FEB_2026 = 46023, 46054


def _make_xlsx(rows: dict) -> bytes:
    """rows = {row_number: {col_letter: value}}; str -> inline string, else number."""
    NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    def cell(col, rn, val):
        ref = f"{col}{rn}"
        if isinstance(val, str):
            return f'<c r="{ref}" t="inlineStr"><is><t>{val}</t></is></c>'
        return f'<c r="{ref}"><v>{val}</v></c>'

    body = []
    for rn in sorted(rows):
        cells = "".join(cell(c, rn, v) for c, v in rows[rn].items())
        body.append(f'<row r="{rn}">{cells}</row>')
    sheet = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{NS}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


@pytest.fixture
def water_file(tmp_path):
    rows = {
        8: {"A": "UNIT", "B": "TENANT NAME", "E": JAN_2026, "F": FEB_2026},
        10: {"A": "U1", "B": "Tenant One", "C": "CLOSING RDG", "E": 100, "F": 110},
        11: {"C": "UNITS CONSUMED", "E": 10, "F": 10},
        12: {"C": "VALUE (KSHS)", "E": 1500, "F": 1500},
        14: {"A": "COMMON SERVICES", "B": "Landlord", "C": "CLOSING RDG", "E": 500, "F": 600},
        15: {"C": "UNITS CONSUMED", "E": 100, "F": 100},
        16: {"C": "VALUE (KSHS)", "E": 15000, "F": 15000},
    }
    path = tmp_path / "water.xlsx"
    path.write_bytes(_make_xlsx(rows))
    return str(path)


@pytest.fixture
def tenant(db):
    building = Building.objects.create(name="Donholm", total_floors=1)
    unit = Unit.objects.create(
        building=building, label="U1", monthly_rent=Decimal("10000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Tenant", last_name="One", id_number="10101010",
        phone="+254700000001", unit=unit, monthly_rent=Decimal("10000"),
        move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
    )


@pytest.mark.django_db
class TestImportWaterCharges:
    def test_creates_charges_per_month(self, tenant, water_file):
        call_command("import_water_charges", water_file)
        charges = UtilityCharge.objects.filter(tenant=tenant).order_by("period_month")
        assert charges.count() == 2
        jan, feb = charges
        assert (jan.period_month, jan.period_year) == (1, 2026)
        assert jan.amount == Decimal("1500.00")
        assert jan.units == Decimal("10")
        assert jan.closing_reading == Decimal("100")
        # Feb's opening reading carries over from Jan's closing.
        assert feb.opening_reading == Decimal("100")
        assert feb.closing_reading == Decimal("110")

    def test_skips_common_services(self, tenant, water_file):
        call_command("import_water_charges", water_file)
        # No landlord/common charge leaks onto the tenant, and the big 15,000
        # common value never appears as a charge.
        assert not UtilityCharge.objects.filter(amount=Decimal("15000.00")).exists()

    def test_is_idempotent(self, tenant, water_file):
        call_command("import_water_charges", water_file)
        call_command("import_water_charges", water_file)
        assert UtilityCharge.objects.filter(tenant=tenant).count() == 2

    def test_dry_run_writes_nothing(self, tenant, water_file):
        call_command("import_water_charges", water_file, "--dry-run")
        assert UtilityCharge.objects.filter(tenant=tenant).count() == 0
