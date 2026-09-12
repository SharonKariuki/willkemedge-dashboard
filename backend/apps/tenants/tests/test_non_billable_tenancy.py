"""A caretaker is housed, not let to — the billing machinery must leave them alone.

The caretakers on the farms and at the Karen residence occupy their house as
part of their job. Recording that occupancy means an active tenant on an
occupied unit, which is exactly the shape every scheduled job looks for. Zero
rent is not enough to keep them out of it: the monthly run would raise a 0.00
arrears row each month, and the reminder and statement jobs walk ACTIVE tenants
rather than unpaid ones, so each caretaker would get chased by SMS and emailed a
statement for a balance that does not exist.
"""
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.buildings.models import (
    Building,
    PropertyType,
    Unit,
    UnitStatus,
)
from apps.buildings.services import recalculate_unit_status
from apps.payments.models import Arrears
from apps.payments.tasks import (
    billable_active_tenants,
    generate_monthly_arrears,
    send_arrears_reminders,
    send_rent_reminders,
)
from apps.tenants.models import Tenant, TenantStatus


def _september():
    """Freeze 'now' well past every tenancy's move-in month."""
    return timezone.make_aware(dt.datetime(2026, 9, 12, 9, 0))


class NonBillableTenancyTests(TestCase):
    def setUp(self):
        self.rental = Building.objects.create(name="Road Block Eldoret", code="RB")
        self.farm = Building.objects.create(
            name="Wilkem Farm, Nyariacho Nyamira", code="FNN",
            property_type=PropertyType.FARM,
        )
        for target in ("apps.payments.tasks.timezone.now",):
            patcher = patch(target, return_value=_september())
            patcher.start()
            self.addCleanup(patcher.stop)

        self.paying = self._tenant(
            self.rental, "RB101", rent="7000", is_billable=True,
        )
        self.caretaker = self._tenant(
            self.farm, "FNNCH", rent="0", is_billable=False,
        )

    def _tenant(self, building, label, *, rent, is_billable):
        unit = Unit.objects.create(
            building=building, label=label, monthly_rent=Decimal(rent),
            status=UnitStatus.OCCUPIED_UNPAID,
        )
        return Tenant.objects.create(
            first_name="T", last_name=label, id_number=f"PENDING-{label}",
            phone="+254700000000", email=f"{label.lower()}@example.com",
            unit=unit, monthly_rent=Decimal(rent),
            move_in_date=dt.date(2026, 7, 1),
            status=TenantStatus.ACTIVE, is_billable=is_billable,
        )

    # --- the shared filter -------------------------------------------------

    def test_billable_active_tenants_excludes_the_caretaker(self):
        found = set(billable_active_tenants("unit").values_list("id", flat=True))
        assert found == {self.paying.id}

    def test_billable_active_tenants_still_excludes_moved_out_tenants(self):
        self.paying.status = TenantStatus.MOVED_OUT
        self.paying.save(update_fields=["status"])
        assert billable_active_tenants().count() == 0

    def test_tenancies_are_billable_by_default(self):
        """The exemption must be opt-in — every ordinary letting is charged."""
        assert self._tenant(self.rental, "RB102", rent="5000", is_billable=True).is_billable
        assert Tenant._meta.get_field("is_billable").default is True

    # --- the monthly rent run ----------------------------------------------

    def test_monthly_run_bills_the_letting_but_not_the_caretaker(self):
        generate_monthly_arrears()

        assert Arrears.objects.filter(tenant=self.paying).exists()
        assert not Arrears.objects.filter(tenant=self.caretaker).exists()

    def test_monthly_run_raises_no_zero_row_even_after_repeated_runs(self):
        """The bug this guards: a 0.00 arrears row per caretaker per month."""
        generate_monthly_arrears()
        generate_monthly_arrears()

        assert Arrears.objects.filter(tenant=self.caretaker).count() == 0

    # --- the reminder jobs --------------------------------------------------

    def _chased_by(self, job):
        with patch("apps.payments.notification_services.dispatch_notification") as dispatch:
            job()
        return {c.args[0].tenant_id for c in dispatch.call_args_list if c.args}

    def test_rent_reminders_skip_the_caretaker(self):
        # Both due on the 14th, two days out, so the job has a live reason to
        # message each of them. Asserting the paying tenant IS chased keeps the
        # test from passing merely because nothing was sent at all.
        Tenant.objects.update(due_day=14)

        chased = self._chased_by(send_rent_reminders)

        assert self.paying.id in chased
        assert self.caretaker.id not in chased

    def test_arrears_reminders_skip_the_caretaker(self):
        # An uncleared balance for the CURRENT period, past the due day — the
        # exact state the job chases. The caretaker is given one too, so what
        # excludes them is the exemption and not an empty ledger.
        for tenant in (self.paying, self.caretaker):
            Arrears.objects.create(
                tenant=tenant, period_month=9, period_year=2026,
                expected_rent=tenant.monthly_rent, amount_paid=Decimal("0"),
                balance=Decimal("7000"), is_cleared=False,
            )

        chased = self._chased_by(send_arrears_reminders)

        assert self.paying.id in chased
        assert self.caretaker.id not in chased

    # --- unit status --------------------------------------------------------

    def test_rent_free_unit_reads_as_settled_not_unpaid(self):
        """Owing nothing and paying nothing is settled, not in arrears.

        Before this, a caretaker's unit sat on Occupied - Unpaid permanently and
        was counted as unpaid in the dashboard's occupancy breakdown.
        """
        unit = self.caretaker.unit
        recalculate_unit_status(unit, Decimal("0"), obligation=Decimal("0"))
        unit.refresh_from_db()

        assert unit.status == UnitStatus.OCCUPIED_PAID

    def test_a_real_letting_that_has_paid_nothing_is_still_unpaid(self):
        unit = self.paying.unit
        recalculate_unit_status(unit, Decimal("0"), obligation=Decimal("7000"))
        unit.refresh_from_db()

        assert unit.status == UnitStatus.OCCUPIED_UNPAID
