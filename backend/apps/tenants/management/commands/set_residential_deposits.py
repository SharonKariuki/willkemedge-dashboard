"""
Bring residential security deposits onto the one-month rule.

Marion Munyinyi on MR202 is the case the owner raised: rent 20,000, deposit
0.00 on the card. She is not unusual — the rent-roll imports carry no deposit
column and load ``deposit_paid`` as 0, so every tenancy onboarded that way has
sat at zero ever since. The commercial arcade was brought onto its three-month
rule by ``apply_matasia_answers``; the residential side never had an equivalent.

What it changes
---------------
Active RESIDENTIAL tenancies whose deposit is unrecorded (0.00) are set to one
month's rent. Commercial lettings are left alone entirely — they take three
months and are ``apply_matasia_answers``' business, not this command's.

What it will not change without being told
------------------------------------------
A deposit that is non-zero but below the rule is REPORTED, not raised. Zero
means "never recorded"; 15,000 against a 20,000 rent means someone wrote down a
figure, and quietly restating it would destroy the only record that a 5,000
shortfall exists. ``--raise-short`` opts into changing those too, once the
landlord has decided that is what they are.

A deposit above the rule is always reported and never touched. MCG05 sat at
390,780 against an expected 259,500 because an odd figure went unquestioned —
an excess is a question, not a rounding error.

Tenancies with no rent are skipped: a deposit of 0 against a rent of 0 is not a
defect, and one month of nothing is not a deposit.

The rule itself lives in ``apps.tenants.deposits`` so this command, the tenant
API and ``check_data_integrity`` cannot drift on what a deposit should be.

Like the commercial deposit step, this sets the ``deposit_paid`` field and
posts nothing to the ledger — it records what is held, it does not claim cash
moved today.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe.

Usage:
    python manage.py set_residential_deposits
    python manage.py set_residential_deposits --apply
    python manage.py set_residential_deposits --raise-short --apply
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.tenants.deposits import expected_deposit

ZERO = Decimal("0.00")


class Command(BaseCommand):
    help = (
        "Set unrecorded residential security deposits to one month's rent. "
        "Commercial lettings are left alone. Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")
        parser.add_argument(
            "--raise-short", action="store_true",
            help="Also raise deposits that are recorded but below one month's rent.",
        )

    def handle(self, *args, **opts):
        from apps.buildings.models import UnitClassification
        from apps.tenants.models import Tenant, TenantStatus

        apply = opts["apply"]
        raise_short = opts["raise_short"]

        tenants = (
            Tenant.objects.filter(
                status=TenantStatus.ACTIVE,
                unit__classification=UnitClassification.RESIDENTIAL,
            )
            .select_related("unit", "unit__building")
            .order_by("unit__building__code", "unit__label")
        )

        unrecorded, short, over, ok, no_rent = [], [], [], [], []
        for tenant in tenants:
            rent = Decimal(tenant.monthly_rent or ZERO)
            held = Decimal(tenant.deposit_paid or ZERO)
            want = expected_deposit(tenant)
            if rent <= ZERO:
                no_rent.append(tenant)
            elif held == want:
                ok.append(tenant)
            elif held == ZERO:
                unrecorded.append((tenant, want))
            elif held < want:
                short.append((tenant, held, want))
            else:
                over.append((tenant, held, want))

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\nResidential security deposits — one month's rent"
        ))

        to_write = list(unrecorded)
        if raise_short:
            to_write += [(t, want) for t, _held, want in short]

        if unrecorded:
            self.stdout.write(f"\nUnrecorded ({len(unrecorded)}) — 0.00 -> one month's rent:")
            for tenant, want in unrecorded:
                self.stdout.write(f"  {self._label(tenant):<10} {tenant.full_name:<28} -> {want}")

        if short:
            verb = "will be raised" if raise_short else "REPORTED ONLY — pass --raise-short to change"
            self.stdout.write(self.style.WARNING(f"\nBelow the rule ({len(short)}) — {verb}:"))
            for tenant, held, want in short:
                self.stdout.write(
                    f"  {self._label(tenant):<10} {tenant.full_name:<28} "
                    f"holds {held}, rule says {want} (short {want - held})"
                )

        if over:
            self.stdout.write(self.style.WARNING(
                f"\nAbove the rule ({len(over)}) — never changed, decide these individually:"
            ))
            for tenant, held, want in over:
                self.stdout.write(
                    f"  {self._label(tenant):<10} {tenant.full_name:<28} "
                    f"holds {held}, rule says {want} (over {held - want})"
                )

        if no_rent:
            self.stdout.write(self.style.NOTICE(
                f"\nNo rent on record ({len(no_rent)}) — skipped, one month of nothing is not a deposit:"
            ))
            for tenant in no_rent:
                self.stdout.write(f"  {self._label(tenant):<10} {tenant.full_name}")

        self.stdout.write(f"\nAlready on the rule: {len(ok)}")

        if not to_write:
            self.stdout.write(self.style.SUCCESS("\nNothing to change."))
            return

        if not apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {len(to_write)} deposit(s) would be set. Re-run with --apply."
            ))
            return

        with transaction.atomic():
            for tenant, want in to_write:
                tenant.deposit_paid = want
                tenant.save(update_fields=["deposit_paid", "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"\nSet {len(to_write)} deposit(s) to one month's rent."))

    def _label(self, tenant):
        return tenant.unit.label if tenant.unit else "(no unit)"
