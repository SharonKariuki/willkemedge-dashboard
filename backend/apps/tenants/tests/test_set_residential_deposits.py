"""
Tests for bringing residential deposits onto the one-month rule.

The distinction that matters: 0.00 means "never recorded" and is filled; a
recorded figure below the rule is a shortfall someone wrote down, and quietly
restating it destroys the only evidence it exists.
"""
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.tenants.models import Tenant, TenantStatus

D = Decimal


@pytest.fixture
def portfolio(db):
    building = Building.objects.create(name="Wilkem Edge", code="WEP", total_floors=3)

    def let(label, classification, rent, held, status=TenantStatus.ACTIVE):
        unit = Unit.objects.create(
            building=building, label=label, monthly_rent=D(rent),
            classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name=label, last_name="Tenant", id_number=f"ID-{label}",
            phone=f"+2547222222{len(label):02d}", unit=unit, monthly_rent=D(rent),
            deposit_paid=D(held), move_in_date="2026-07-01", status=status,
        )

    return {
        # Marion's case: rent on record, deposit never captured.
        "unrecorded": let("WEP01", UnitClassification.RESIDENTIAL, "20000", "0"),
        "short": let("WEP02", UnitClassification.RESIDENTIAL, "20000", "15000"),
        "over": let("WEP03", UnitClassification.RESIDENTIAL, "20000", "50000"),
        "ok": let("WEP04", UnitClassification.RESIDENTIAL, "20000", "20000"),
        "no_rent": let("WEP05", UnitClassification.RESIDENTIAL, "0", "0"),
        "commercial": let("WEP06", UnitClassification.BUSINESS, "24000", "0"),
        "moved_out": let("WEP07", UnitClassification.RESIDENTIAL, "20000", "0",
                         status=TenantStatus.MOVED_OUT),
    }


def _held(tenant):
    tenant.refresh_from_db()
    return tenant.deposit_paid


class TestDryRun:
    def test_writes_nothing_without_apply(self, portfolio):
        call_command("set_residential_deposits")

        assert _held(portfolio["unrecorded"]) == D("0.00")

    def test_reports_what_it_would_do(self, portfolio, capsys):
        call_command("set_residential_deposits")

        assert "DRY-RUN" in capsys.readouterr().out


class TestUnrecordedDeposits:
    def test_zero_becomes_one_months_rent(self, portfolio):
        """Marion's case: rent 20,000, deposit 0.00."""
        call_command("set_residential_deposits", "--apply")

        assert _held(portfolio["unrecorded"]) == D("20000.00")

    def test_a_deposit_already_on_the_rule_is_untouched(self, portfolio):
        call_command("set_residential_deposits", "--apply")

        assert _held(portfolio["ok"]) == D("20000.00")


class TestRecordedButShort:
    def test_is_reported_not_raised_by_default(self, portfolio, capsys):
        call_command("set_residential_deposits", "--apply")

        assert _held(portfolio["short"]) == D("15000.00"), "a written-down figure was restated"
        assert "--raise-short" in capsys.readouterr().out

    def test_is_raised_when_asked(self, portfolio):
        call_command("set_residential_deposits", "--raise-short", "--apply")

        assert _held(portfolio["short"]) == D("20000.00")


class TestExcessIsNeverTouched:
    def test_over_the_rule_is_left_alone_even_with_raise_short(self, portfolio):
        """MCG05 sat at 390,780 because an odd figure went unquestioned."""
        call_command("set_residential_deposits", "--raise-short", "--apply")

        assert _held(portfolio["over"]) == D("50000.00")

    def test_over_the_rule_is_reported(self, portfolio, capsys):
        call_command("set_residential_deposits")

        assert "Above the rule" in capsys.readouterr().out


class TestScope:
    def test_commercial_is_left_entirely_alone(self, portfolio):
        """Commercial takes three months and is apply_matasia_answers' business."""
        call_command("set_residential_deposits", "--raise-short", "--apply")

        assert _held(portfolio["commercial"]) == D("0.00")

    def test_a_tenancy_with_no_rent_is_skipped(self, portfolio):
        """One month of nothing is not a deposit."""
        call_command("set_residential_deposits", "--apply")

        assert _held(portfolio["no_rent"]) == D("0.00")

    def test_a_former_tenant_is_not_given_a_deposit(self, portfolio):
        call_command("set_residential_deposits", "--apply")

        assert _held(portfolio["moved_out"]) == D("0.00")


class TestIdempotence:
    def test_rerun_changes_nothing_further(self, portfolio):
        call_command("set_residential_deposits", "--apply")
        call_command("set_residential_deposits", "--apply")

        assert _held(portfolio["unrecorded"]) == D("20000.00")

    def test_second_run_reports_nothing_to_change(self, portfolio, capsys):
        call_command("set_residential_deposits", "--apply")
        capsys.readouterr()

        call_command("set_residential_deposits", "--apply")

        assert "Nothing to change" in capsys.readouterr().out
