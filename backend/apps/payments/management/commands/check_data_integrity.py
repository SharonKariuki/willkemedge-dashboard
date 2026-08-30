"""
Assert the invariants the books depend on, and fail loudly when one breaks.

Every check below is something that actually went wrong on this portfolio and
was found by reading a paper statement rather than by the system saying so. The
point of this command is that the system says so next time.

    python manage.py check_data_integrity          # report
    python manage.py check_data_integrity --quiet  # only print failures

Exits non-zero when anything fails, so it works as a cron job, a deploy gate or
a pre-flight before an import. Run it after any bulk load.

What it does NOT do is fix anything. A drift here means a decision is needed —
whether a deposit really is short, whether a tenancy is really let — and those are
the landlord's to make, not this command's.
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand

ZERO = Decimal("0.00")

# Units whose tenancy is deliberately outside the usual rules, with the reason.
# Anything here is reported as an accepted exception rather than a failure, so
# a known oddity does not train people to ignore a red run.
ACCEPTED = {
    # unit label: why it is allowed to differ
}


class Check:
    """One invariant: a name, the question it answers, and the rows that fail."""

    def __init__(self, name, matters):
        self.name = name
        self.matters = matters
        self.failures = []

    def fail(self, subject, detail):
        self.failures.append((subject, detail))


class Command(BaseCommand):
    help = (
        "Assert the data invariants the books depend on — deposits, billing "
        "coverage, duplicate tenancies, rent agreement, unassigned cash. "
        "Exits non-zero on any failure."
    )

    def add_arguments(self, parser):
        parser.add_argument("--quiet", action="store_true", help="Only print failing checks.")
        parser.add_argument(
            "--stale-days", type=int, default=7,
            help="How long an unmatched bank credit may sit before it is a failure (default 7).",
        )

    def handle(self, *args, **opts):
        self.quiet = opts["quiet"]
        checks = [
            self._security_deposits(),
            self._zero_charge_holding_cash(),
            self._one_active_tenant_per_unit(),
            self._tenant_rent_matches_unit(),
            self._kra_pin_not_shared_across_entities(),
            self._current_month_is_billed(),
            self._unassigned_cash(opts["stale_days"]),
            self._opening_month_not_double_charged(),
        ]

        failed = [c for c in checks if c.failures]
        for check in checks:
            if check.failures:
                self.stdout.write(self.style.ERROR(f"\nFAIL  {check.name}"))
                self.stdout.write(f"      {check.matters}")
                for subject, detail in check.failures:
                    self.stdout.write(f"        · {subject}: {detail}")
            elif not self.quiet:
                self.stdout.write(self.style.SUCCESS(f"ok    {check.name}"))

        total = sum(len(c.failures) for c in failed)
        if failed:
            self.stdout.write(self.style.ERROR(
                f"\n{len(failed)} check(s) failed, {total} row(s) affected."
            ))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(f"\nAll {len(checks)} checks passed."))

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _live_tenants():
        from apps.tenants.models import Tenant, TenantStatus

        return (
            Tenant.objects
            .filter(status__in=[TenantStatus.ACTIVE, TenantStatus.NOTICE_GIVEN])
            .select_related("unit", "unit__building")
        )

    @staticmethod
    def _label(tenant):
        return tenant.unit.label if tenant.unit else "(no unit)"

    # -- checks -------------------------------------------------------------

    def _security_deposits(self):
        """MCG05 sat at 390,780 against an expected 259,500 for a month, because
        the figure was transcribed from an old roll and never questioned.

        This used to look at commercial lettings alone, which meant a
        residential deposit could sit at zero indefinitely and nothing said so.
        The rule itself lives in ``apps.tenants.deposits`` — one month's rent,
        three for a commercial letting — so the check and the tenant API cannot
        drift apart.
        """
        from apps.tenants.deposits import (
            deposit_months,
            expected_deposit,
            has_agreed_deposit,
        )

        check = Check(
            "security deposit matches the rule for the letting",
            "A deposit transcribed from an old roll is not a deposit anyone agreed.",
        )
        for t in self._live_tenants():
            if self._label(t) in ACCEPTED:
                continue
            expected = expected_deposit(t)
            if t.deposit_paid != expected:
                # A manually agreed deposit is a figure, not months of rent —
                # printing "1 x 15,000" against an agreed 14,000 would read as
                # though the rule were still in force.
                basis = (
                    "agreed"
                    if has_agreed_deposit(t)
                    else f"{deposit_months(t)} x {t.monthly_rent}"
                )
                check.fail(
                    f"{self._label(t)} {t.full_name}",
                    f"holds {t.deposit_paid}, expected {expected} ({basis})",
                )
        return check

    def _zero_charge_holding_cash(self):
        """RB406 read ~18,000 in credit while owing two months, because its
        arrears rows were raised while the rent still said 0.00."""
        from apps.payments.models import Arrears

        check = Check(
            "no charge raised at zero is holding cash",
            "Cash against a nil obligation reads as credit and the tenant drops out of dunning.",
        )
        rows = (
            Arrears.objects
            .filter(expected_rent=ZERO, amount_paid__gt=ZERO, tenant__monthly_rent__gt=ZERO)
            .select_related("tenant", "tenant__unit")
        )
        for a in rows:
            check.fail(
                f"{self._label(a.tenant)} {a.tenant.full_name}",
                f"{a.period_month}/{a.period_year} billed 0.00 but holds {a.amount_paid}",
            )
        return check

    def _one_active_tenant_per_unit(self):
        """The 15-17 Aug roster correction left two live tenancies on five units
        and August's money landed on the retired copy of each."""
        from collections import defaultdict

        check = Check(
            "one live tenancy per unit",
            "A second live tenancy on a unit is where an incoming payment goes to the wrong person.",
        )
        by_unit = defaultdict(list)
        for t in self._live_tenants():
            if t.unit:
                by_unit[t.unit.label].append(t)
        for label, tenants in sorted(by_unit.items()):
            if len(tenants) > 1:
                check.fail(label, "; ".join(f"#{t.pk} {t.full_name} ({t.status})" for t in tenants))
        return check

    def _tenant_rent_matches_unit(self):
        """The unit roll is the authoritative rent; a tenancy that disagrees
        with it bills one figure and reports another."""
        check = Check(
            "tenancy rent agrees with the unit",
            "Two rents for one unit means the bill and the rent roll disagree.",
        )
        for t in self._live_tenants():
            if not t.unit or self._label(t) in ACCEPTED:
                continue
            if t.unit.monthly_rent != t.monthly_rent:
                check.fail(
                    f"{self._label(t)} {t.full_name}",
                    f"tenancy {t.monthly_rent} vs unit {t.unit.monthly_rent}",
                )
        return check

    def _kra_pin_not_shared_across_entities(self):
        """The Shamiri Place and Ignite Energy were recorded under one PIN.
        Two limited companies never share one, and a wrong PIN voids a VAT
        invoice. One person holding two units legitimately shares theirs, so
        the failure is a shared PIN across DIFFERENT names."""
        from collections import defaultdict

        check = Check(
            "a KRA PIN is not shared across different names",
            "A wrong PIN makes a VAT invoice invalid.",
        )
        by_pin = defaultdict(set)
        holders = defaultdict(list)
        for t in self._live_tenants():
            if not t.kra_pin:
                continue
            by_pin[t.kra_pin].add(t.full_name.strip().lower())
            holders[t.kra_pin].append(f"{self._label(t)} {t.full_name}")
        for pin, names in sorted(by_pin.items()):
            if len(names) > 1:
                check.fail(pin, " | ".join(holders[pin]))
        return check

    def _current_month_is_billed(self):
        """790,000 went unbilled because the scheduler was firing into an empty
        token and nobody noticed for a month."""
        from apps.payments.models import Arrears

        today = _dt.date.today()
        check = Check(
            f"every live tenancy is billed for {today.month}/{today.year}",
            "An unbilled month is invisible: no arrears row, no reminder, no report line.",
        )
        billed = set(
            Arrears.objects
            .filter(period_year=today.year, period_month=today.month)
            .values_list("tenant_id", flat=True)
        )
        for t in self._live_tenants():
            # Nobody owes rent for a month they moved in after.
            if t.move_in_date and (t.move_in_date.year, t.move_in_date.month) > (today.year, today.month):
                continue
            if t.pk not in billed:
                check.fail(f"{self._label(t)} {t.full_name}", "no charge raised this month")
        return check

    def _unassigned_cash(self, stale_days):
        """Elimisha's 4,700 sat unmatched because PesaLink carries no bill ref.
        Money in the queue is money not on anyone's account."""
        from django.utils import timezone

        from apps.payments.models import CoopIpnEvent

        cutoff = timezone.now() - _dt.timedelta(days=stale_days)
        check = Check(
            f"no bank credit unassigned for more than {stale_days} days",
            "An unmatched credit is real money missing from a tenant's balance.",
        )
        stale = CoopIpnEvent.objects.filter(status="unmatched", received_at__lt=cutoff)
        for e in stale.order_by("received_at"):
            check.fail(
                e.transaction_id,
                f"{e.amount} received {e.received_at:%d %b %Y} — {(e.narration or '')[:60]}",
            )
        return check

    def _opening_month_not_double_charged(self):
        """MCG10's August read 95,340 against a statement saying 85,140: a July
        water charge of 10,200 rode on top of a 43,800 brought-forward, which
        already contained it."""
        from apps.payments.models import Arrears, UtilityCharge

        check = Check(
            "an opening balance does not sit alongside its own charges",
            "A brought-forward already contains every charge to that date; a second one double-counts.",
        )
        openings = Arrears.objects.filter(
            waive_notes__icontains="Opening position carried"
        ).select_related("tenant", "tenant__unit")
        for a in openings:
            clash = UtilityCharge.objects.filter(
                tenant_id=a.tenant_id, period_year=a.period_year, period_month=a.period_month,
            )
            total = sum((c.amount for c in clash), ZERO)
            if total:
                check.fail(
                    f"{self._label(a.tenant)} {a.tenant.full_name}",
                    f"{a.period_month}/{a.period_year} opening {a.expected_rent} "
                    f"sits alongside {total} of charges",
                )
        return check
