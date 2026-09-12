"""
The water tariff is per property, not portfolio-wide.

Dr Osoro's rates (Sept 2026):
    Donholm Nairobi        KES 150 / unit
    Matasia Commercial     KES 200 / unit
    Matasia Residential    KES 200 / unit

Migration 0009 raised every building sitting on 150 to 200, which swept Donholm
up with the two Matasia buildings. 0010 puts it back and pins all three.
"""
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.meter_service import bill_meter_reading
from apps.payments.statement_generator import DEFAULTS, build_context
from apps.tenants.models import Tenant, TenantStatus

RATES = [
    ("DON", "Wilkem Edge Apartments - Donholm Nairobi", Decimal("150.00")),
    ("MC", "Wilkem Edge Business Arcade - Matasia Commercial", Decimal("200.00")),
    ("MAR", "Wilkem Edge Residential Apartments - Matasia", Decimal("200.00")),
]


def _tenant(code, name, rate, label, idx):
    building = Building.objects.create(
        name=name, code=code, total_floors=1, water_rate_per_unit=rate,
    )
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal("20000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="T", last_name=str(idx), id_number=f"ID{idx}",
        phone=f"+25470000000{idx}", unit=unit, monthly_rent=Decimal("20000"),
        move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
    )


@pytest.mark.django_db
class TestPerBuildingTariff:
    @pytest.mark.parametrize("code,name,rate", RATES)
    def test_consumption_priced_at_the_buildings_own_rate(self, code, name, rate):
        """10 units of water costs 1,500 at Donholm and 2,000 at Matasia."""
        tenant = _tenant(code, name, rate, f"{code}101", 1)
        charge = bill_meter_reading(
            tenant=tenant, period_month=3, period_year=2026,
            opening_reading=100, closing_reading=110,
        )
        assert charge.units == Decimal("10.00")
        assert charge.amount == (Decimal("10") * rate).quantize(Decimal("0.01"))
        assert charge.rate_per_unit() == rate

    def test_two_buildings_bill_the_same_consumption_differently(self):
        donholm = _tenant(*RATES[0], "DON1A", 1)
        matasia = _tenant(*RATES[1], "MCG01", 2)

        common = dict(period_month=3, period_year=2026, opening_reading=0, closing_reading=8)
        assert bill_meter_reading(tenant=donholm, **common).amount == Decimal("1200.00")
        assert bill_meter_reading(tenant=matasia, **common).amount == Decimal("1600.00")

    def test_charge_keeps_the_rate_it_was_billed_at(self):
        """Moving the building's tariff must not re-price a charge already raised."""
        tenant = _tenant(*RATES[0], "DON2A", 3)
        charge = bill_meter_reading(
            tenant=tenant, period_month=3, period_year=2026,
            opening_reading=0, closing_reading=4,
        )
        tenant.unit.building.water_rate_per_unit = Decimal("200.00")
        tenant.unit.building.save(update_fields=["water_rate_per_unit"])

        charge.refresh_from_db()
        assert charge.amount == Decimal("600.00")
        assert charge.rate_per_unit() == Decimal("150.00")
        assert "@ KES 150" in charge.description()


class TestStatementGeneratorFallback:
    def test_default_is_donholms_rate(self):
        """DEFAULTS is the Donholm template, so its water rate is Donholm's."""
        assert DEFAULTS["water_rate"] == 150

    def test_building_block_overrides_the_tariff(self):
        """A Matasia statement carrying readings but no rate prices at 200."""
        ctx = build_context({
            "unit": "MCG01",
            "building": {"water_rate": 200},
            "transactions": [
                {"date": "3 Mar 2026", "type": "water", "label": "Water usage - Feb. '26",
                 "opening_reading": 1000, "closing_reading": 1007},
            ],
        })
        row = ctx["rows"][0]
        assert row["description_lines"][0] == "Water usage - Feb. '26 (7 units @ KES 200)"
        assert Decimal(str(row["invoice_amount"]).replace(",", "")) == Decimal("1400")

    def test_explicit_rate_on_the_transaction_still_wins(self):
        ctx = build_context({
            "unit": "DON1A",
            "building": {"water_rate": 200},
            "transactions": [
                {"date": "3 Mar 2026", "type": "water", "label": "Water usage - Feb. '26",
                 "opening_reading": 1000, "closing_reading": 1007, "rate": 150},
            ],
        })
        assert ctx["rows"][0]["description_lines"][0] == "Water usage - Feb. '26 (7 units @ KES 150)"


@pytest.mark.django_db
class TestMigrationDataStep:
    """The 0010 data step, exercised directly against the real Building model.

    Running it through the migration executor would only re-test Django; what
    is worth pinning is the mapping itself, because 0009 got exactly this
    wrong — it keyed off the old rate instead of the property.
    """

    @staticmethod
    def _run():
        from importlib import import_module

        module = import_module("apps.buildings.migrations.0010_water_rate_per_building")

        class _FakeApps:
            @staticmethod
            def get_model(app_label, model_name):
                assert (app_label, model_name) == ("buildings", "Building")
                return Building

        module.set_rates(_FakeApps, None)

    def test_donholm_goes_back_to_150_and_matasia_stays_at_200(self):
        for code, name, _rate in RATES:
            Building.objects.create(
                name=name, code=code, total_floors=1,
                water_rate_per_unit=Decimal("200.00"),
            )
        self._run()

        by_code = {b.code: b.water_rate_per_unit for b in Building.objects.all()}
        assert by_code["DON"] == Decimal("150.00")
        assert by_code["MC"] == Decimal("200.00")
        assert by_code["MAR"] == Decimal("200.00")

    def test_a_building_outside_the_three_is_left_alone(self):
        Building.objects.create(
            name="Wilkem Edge Apartments - Road Block Eldoret", code="RB",
            total_floors=1, water_rate_per_unit=Decimal("200.00"),
        )
        self._run()
        assert Building.objects.get(code="RB").water_rate_per_unit == Decimal("200.00")

    def test_donholm_without_a_short_code_is_still_matched_by_name(self):
        """The name fallback catches a building loaded before the coding scheme."""
        Building.objects.create(
            name="Wilkem Edge Apartments, Donholm Estate", code=None,
            total_floors=1, water_rate_per_unit=Decimal("200.00"),
        )
        self._run()
        assert Building.objects.get(code=None).water_rate_per_unit == Decimal("150.00")
