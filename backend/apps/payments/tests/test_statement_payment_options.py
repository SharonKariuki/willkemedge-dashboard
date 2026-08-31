"""
Statement masthead and payment options.

Two corrections the landlord marked on the Sidai Lonestar (MCG05) statement:

  * the masthead must name the legal entity that issues the statement, not a
    property that happens to be the oldest default in the codebase;
  * the Paybill row must carry the account number the tenant has to quote,
    in its coded '90290#<unit>' form. A paybill printed without an account
    lands the payment in the unmatched queue.
"""
import datetime as _dt
from decimal import Decimal

import pytest
from django.template.loader import render_to_string

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.payments.statement_service import (
    DEFAULT_PAYBILL_NUMBER,
    build_statement,
)
from apps.tenants.models import Tenant, TenantStatus

AS_OF = _dt.date(2026, 8, 29)


def _make_tenant(label="MCG05", **building_kwargs):
    """A tenant on a building configured however the test needs."""
    building = Building.objects.create(
        name=f"B{label}", code=label[:3], total_floors=1, **building_kwargs
    )
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal("12000"),
        classification=UnitClassification.BUSINESS,
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Sidai", last_name=label, id_number=f"ID-{label}",
        phone="+254722301981", email="sidai@example.com", unit=unit,
        monthly_rent=Decimal("12000"), move_in_date="2026-01-01",
        status=TenantStatus.ACTIVE,
    )


@pytest.mark.django_db
class TestMasthead:
    def test_unconfigured_building_names_the_company(self):
        """A building with no legal_name must not borrow another property's name."""
        tenant = _make_tenant()
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        assert st["entity_name"] == "Wilkem Ventures Company Limited"
        assert "Wilkem Edge Apartments" not in st["entity_name"]

    def test_building_legal_name_still_wins(self):
        tenant = _make_tenant(legal_name="Some Other Holdings Ltd")
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        assert st["entity_name"] == "Some Other Holdings Ltd"

    def test_company_name_reaches_the_pdf(self):
        tenant = _make_tenant()
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        html = render_to_string("payments/statement_pdf.html", st)
        assert "Wilkem Ventures Company Limited" in html


@pytest.mark.django_db
class TestPaybillAccount:
    def test_default_paybill_carries_its_account_number(self):
        """The bug behind the landlord's 'Include Account number' note.

        The paybill number fell back to the Wilkem default while the account
        stayed blank, because the fallback was gated on the building's own
        (unset) paybill field.
        """
        tenant = _make_tenant("MCG05")
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        assert st["paybill_number"] == DEFAULT_PAYBILL_NUMBER
        assert st["paybill_account"] == "90290#MCG05"

    def test_account_number_is_coded_to_the_unit(self):
        tenant = _make_tenant("RB305")
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        assert st["paybill_account"] == "90290#RB305"

    def test_account_number_reaches_the_pdf(self):
        tenant = _make_tenant("MCG05")
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        html = render_to_string("payments/statement_pdf.html", st)
        assert "90290#MCG05" in html
        assert "Account No." in html

    def test_account_number_reaches_the_email(self):
        from apps.payments.notifications import statement_email_html

        tenant = _make_tenant("MCG05")
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        html = statement_email_html(tenant.full_name, st)
        assert "90290#MCG05" in html

    def test_building_with_its_own_paybill_keeps_its_own_account(self):
        tenant = _make_tenant(
            "XY1", paybill_number="555111", paybill_account_format="ACC-{unit}",
        )
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        assert st["paybill_number"] == "555111"
        assert st["paybill_account"] == "ACC-XY1"

    def test_own_paybill_with_no_account_format_stays_blank(self):
        """Blank on a configured paybill is deliberate, not a gap to fill in.

        Such a paybill takes no account number, so the Wilkem default must not
        be substituted into it.
        """
        tenant = _make_tenant("XY2", paybill_number="555111")
        st = build_statement(tenant, statement_date=AS_OF, as_of=AS_OF)
        assert st["paybill_number"] == "555111"
        assert st["paybill_account"] == ""
