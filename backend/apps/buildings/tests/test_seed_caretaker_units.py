"""Tests for seed_caretaker_units (a rent-free caretaker on each non-rental property)."""
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.tasks import billable_active_tenants
from apps.tenants.models import Tenant

LABELS = ["FSCH", "FMNCH", "FNNCH", "KNCH"]


def _run(*args):
    out = StringIO()
    call_command("seed_caretaker_units", *args, stdout=out, stderr=out)
    return out.getvalue()


@pytest.fixture
def properties(db):
    call_command("seed_special_properties", stdout=StringIO())


@pytest.mark.django_db
class TestSeedCaretakerUnits:
    def test_creates_one_unit_and_one_caretaker_per_property(self, properties):
        _run()

        assert Unit.objects.filter(label__in=LABELS).count() == 4
        assert Tenant.objects.count() == 4

    def test_each_unit_lands_on_its_own_property(self, properties):
        _run()

        pairs = {u.label: u.building.code for u in Unit.objects.select_related("building")}
        assert pairs == {"FSCH": "FS", "FMNCH": "FMN", "FNNCH": "FNN", "KNCH": "KN"}

    def test_caretakers_are_rent_free_and_excluded_from_billing(self, properties):
        _run()

        for tenant in Tenant.objects.all():
            assert tenant.monthly_rent == Decimal("0")
            assert tenant.is_billable is False
        # The point of the flag: the four scheduled jobs never see them.
        assert billable_active_tenants().count() == 0

    def test_the_units_read_as_occupied_not_vacant(self, properties):
        _run()

        assert not Unit.objects.filter(status=UnitStatus.VACANT).exists()
        assert Unit.objects.filter(status=UnitStatus.OCCUPIED_PAID).count() == 4

    def test_is_idempotent(self, properties):
        _run()
        out = _run()

        assert "0 unit(s) created, 0 caretaker(s) created, 4 already on record" in out
        assert Tenant.objects.count() == 4

    def test_dry_run_writes_nothing(self, properties):
        out = _run("--dry-run")

        assert "DRY RUN" in out
        assert not Unit.objects.exists()
        assert not Tenant.objects.exists()

    def test_real_details_can_be_supplied_instead_of_a_placeholder(self, properties):
        _run("--caretaker", "FSCH", "Joseph Kiplagat", "0712345678", "12345678")

        caretaker = Tenant.objects.get(unit__label="FSCH")
        assert caretaker.full_name == "Joseph Kiplagat"
        assert caretaker.phone == "0712345678"
        assert caretaker.id_number == "12345678"

    def test_placeholders_are_flagged_so_they_are_not_forgotten(self, properties):
        out = _run()

        assert "placeholder" in out
        assert "4 caretaker(s) still carry a placeholder ID" in out

    def test_an_unknown_unit_is_refused_rather_than_silently_ignored(self, properties):
        out = _run("--caretaker", "NOPE", "Someone Else", "0700000000", "999")

        assert "Unknown caretaker unit(s): NOPE" in out
        assert not Tenant.objects.exists()

    def test_it_says_so_when_the_properties_have_not_been_seeded(self, db):
        out = _run()

        assert "No building found for code(s)" in out
        assert "seed_special_properties" in out

    def test_it_still_seeds_the_properties_that_do_exist(self, db):
        Building.objects.create(code="KN", name="Wilkem Residence, The Baobab Karen")

        _run()

        assert Tenant.objects.count() == 1
        assert Unit.objects.get().label == "KNCH"

    def test_an_existing_caretaker_is_left_alone(self, properties):
        _run("--caretaker", "KNCH", "Mary Atieno", "0720000000", "87654321")
        _run()

        caretaker = Tenant.objects.get(unit__label="KNCH")
        assert caretaker.full_name == "Mary Atieno"
        assert caretaker.id_number == "87654321"
