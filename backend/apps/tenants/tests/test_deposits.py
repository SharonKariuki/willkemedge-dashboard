"""
Tests for the security-deposit rule.

One month's rent for every letting except a commercial one, which takes three.
The rule is derived and never written to ``deposit_paid``: what was received is
a fact, and rounding it up to policy is how an unquestioned figure survives.
"""
from decimal import Decimal

import pytest

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.tenants.deposits import (
    deposit_months,
    deposit_shortfall,
    expected_deposit,
    has_agreed_deposit,
)
from apps.tenants.models import Tenant, TenantStatus

D = Decimal


@pytest.fixture
def portfolio(db):
    building = Building.objects.create(name="Wilkem Edge", code="WET", total_floors=2)

    def let(label, classification, rent, held):
        unit = Unit.objects.create(
            building=building, label=label, monthly_rent=D(rent),
            classification=classification, status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name=label, last_name="Tenant", id_number=f"T-{label}",
            phone=f"+2547000000{len(label):02d}", unit=unit, monthly_rent=D(rent),
            deposit_paid=D(held), move_in_date="2026-07-01", status=TenantStatus.ACTIVE,
        )

    return {
        "residential": let("WET01", UnitClassification.RESIDENTIAL, "20000", "20000"),
        "short": let("WET02", UnitClassification.RESIDENTIAL, "20000", "0"),
        "commercial": let("WET03", UnitClassification.BUSINESS, "24000", "72000"),
    }


class TestDepositMonths:
    def test_residential_takes_one_month(self, portfolio):
        assert deposit_months(portfolio["residential"]) == 1

    def test_commercial_takes_three_months(self, portfolio):
        assert deposit_months(portfolio["commercial"]) == 3

    def test_a_tenancy_with_no_unit_falls_to_one_month(self, db):
        """`Tenant.unit` is non-nullable, so this only arises on an unsaved
        instance — a form being validated, say. It must not raise there."""
        tenant = Tenant(
            first_name="No", last_name="Unit", id_number="T-NONE",
            phone="+254700000099", monthly_rent=D("15000"), deposit_paid=D(0),
        )
        assert deposit_months(tenant) == 1
        assert expected_deposit(tenant) == D("15000.00")


class TestExpectedDeposit:
    def test_residential_is_one_months_rent(self, portfolio):
        assert expected_deposit(portfolio["residential"]) == D("20000.00")

    def test_commercial_is_three_months_rent(self, portfolio):
        assert expected_deposit(portfolio["commercial"]) == D("72000.00")

    def test_zero_rent_expects_zero(self, portfolio):
        tenant = portfolio["residential"]
        tenant.monthly_rent = D(0)
        assert expected_deposit(tenant) == D("0.00")


class TestShortfall:
    def test_no_shortfall_when_the_rule_is_met(self, portfolio):
        assert deposit_shortfall(portfolio["residential"]) == D("0.00")

    def test_an_unrecorded_deposit_is_a_full_shortfall(self, portfolio):
        """The case the card was blind to: nothing held, nothing said."""
        assert deposit_shortfall(portfolio["short"]) == D("20000.00")

    def test_an_excess_is_not_a_shortfall(self, portfolio):
        """Over-held is worth reporting, but it is not money owed."""
        tenant = portfolio["residential"]
        tenant.deposit_paid = D("50000")
        assert deposit_shortfall(tenant) == D("0.00")

    def test_commercial_shortfall_uses_the_three_month_rule(self, portfolio):
        tenant = portfolio["commercial"]
        tenant.deposit_paid = D("24000")
        assert deposit_shortfall(tenant) == D("48000.00")


class TestAgreedDeposit:
    """A deposit agreed at a figure the rule does not produce.

    The card reported a shortfall against money nobody owed — a letting settled
    at 14,000 on a 15,000 rent read as "1,000 short of 15,000". Setting the
    agreed figure is what makes that stop.
    """

    def test_the_rule_governs_when_nothing_is_agreed(self, portfolio):
        tenant = portfolio["residential"]
        assert has_agreed_deposit(tenant) is False
        assert expected_deposit(tenant) == D("20000.00")

    def test_an_agreed_figure_replaces_the_rule(self, portfolio):
        tenant = portfolio["residential"]
        tenant.agreed_deposit = D("14000")
        assert has_agreed_deposit(tenant) is True
        assert expected_deposit(tenant) == D("14000.00")

    def test_meeting_the_agreed_figure_clears_the_shortfall(self, portfolio):
        tenant = portfolio["residential"]
        tenant.monthly_rent = D("15000")
        tenant.deposit_paid = D("14000")
        assert deposit_shortfall(tenant) == D("1000.00")
        tenant.agreed_deposit = D("14000")
        assert deposit_shortfall(tenant) == D("0.00")

    def test_falling_short_of_the_agreed_figure_still_shows(self, portfolio):
        """The override moves the bar; it does not remove it."""
        tenant = portfolio["residential"]
        tenant.agreed_deposit = D("30000")
        assert deposit_shortfall(tenant) == D("10000.00")

    def test_zero_is_agreed_not_blank(self, portfolio):
        """A deposit agreed at nothing is a decision, and must not fall back to
        the rule — only ``None`` does that."""
        tenant = portfolio["short"]
        tenant.agreed_deposit = D("0")
        assert has_agreed_deposit(tenant) is True
        assert expected_deposit(tenant) == D("0.00")
        assert deposit_shortfall(tenant) == D("0.00")

    def test_an_agreed_figure_overrides_the_commercial_rule_too(self, portfolio):
        tenant = portfolio["commercial"]
        tenant.agreed_deposit = D("50000")
        assert expected_deposit(tenant) == D("50000.00")
        assert deposit_months(tenant) == 3  # the rule is unchanged underneath

    def test_it_survives_a_round_trip(self, portfolio):
        tenant = portfolio["residential"]
        tenant.agreed_deposit = D("14000")
        tenant.save(update_fields=["agreed_deposit"])
        assert expected_deposit(Tenant.objects.get(pk=tenant.pk)) == D("14000.00")


class TestTheRuleIsNotWrittenToTheTenant:
    def test_deposit_paid_is_left_alone(self, portfolio):
        """Deriving the expectation must never restate what was received."""
        tenant = portfolio["short"]
        expected_deposit(tenant)
        deposit_shortfall(tenant)
        tenant.refresh_from_db()
        assert tenant.deposit_paid == D("0.00")
