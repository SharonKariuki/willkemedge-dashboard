"""
Take VAT off a commercial letting the landlord does not charge VAT on.

Ticking "No VAT on this letting" stops the NEXT charges carrying 16% VAT. The
months already raised keep the VAT they were billed with, which is what this
command restates: from ``--from`` onward, each of the letting's rent charges is
set to VAT 0 and its balance worked out again. MCG02 was billed 3,600 VAT a
month that the landlord's sheet never charged.

Each row is re-saved, not ``.update()``d, so the accrual ledger re-posts it
off the Arrears post_save signal and 2600 VAT payable follows. A month with a
VAT credit note already issued against it is left alone and reported: taking
its VAT away as well would credit the tenant twice.

Preview is the DEFAULT: the whole change runs and is rolled back. ``--apply``
keeps it. The run also ticks the letting's ``vat_exempt``.

Usage (Render Shell):
    python manage.py clear_vat MCG02 --from 2026-09
    python manage.py clear_vat MCG02 --from 2026-09 --apply
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

ZERO = Decimal("0")


class _Rollback(Exception):
    pass


def _period(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.split("-"))
    except ValueError:
        raise CommandError(f"--from must be YYYY-MM, not {value!r}") from None
    if not 1 <= month <= 12:
        raise CommandError(f"--from must be YYYY-MM, not {value!r}")
    return year, month


class Command(BaseCommand):
    help = "Restate a VAT-exempt letting's rent charges without VAT (preview unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("unit", help="Unit label, e.g. MCG02")
        parser.add_argument("--from", dest="start", required=True, help="First month to restate, YYYY-MM")
        parser.add_argument("--apply", action="store_true", help="Keep the change (default: preview)")

    def handle(self, *args, unit, start, apply, **options):
        from apps.buildings.models import UnitClassification
        from apps.tenants.models import CURRENT_STATUSES, Tenant

        start_year, start_month = _period(start)
        tenants = list(
            Tenant.objects.select_related("unit").filter(unit__label=unit, status__in=CURRENT_STATUSES)
        )
        if len(tenants) != 1:
            raise CommandError(f"{unit}: expected one current tenant, found {len(tenants)}. Nothing was written.")
        tenant = tenants[0]
        if tenant.unit.classification != UnitClassification.BUSINESS:
            raise CommandError(f"{unit} is not a commercial unit; residential rent carries no VAT.")

        self.stdout.write(f"{unit}: {tenant} — {'APPLY' if apply else 'PREVIEW (rolled back)'}")
        try:
            with transaction.atomic():
                cleared = self._clear(tenant, start_year, start_month)
                self.stdout.write(f"VAT taken off: {cleared:,.2f}")
                if not apply:
                    raise _Rollback
        except _Rollback:
            self.stdout.write("Preview only — nothing was kept. Run again with --apply.")

    def _clear(self, tenant, start_year: int, start_month: int) -> Decimal:
        from django.db.models import Q

        from apps.payments.models import Arrears, CreditStatus
        from apps.payments.services import _update_arrears

        if not tenant.vat_exempt:
            tenant.vat_exempt = True
            tenant.save(update_fields=["vat_exempt"])
            self.stdout.write("  ticked 'No VAT on this letting'")

        rows = (
            Arrears.objects.select_for_update()
            .filter(
                Q(period_year__gt=start_year) | Q(period_year=start_year, period_month__gte=start_month),
                tenant=tenant,
                expected_vat__gt=0,
            )
            .order_by("period_year", "period_month")
        )
        cleared = ZERO
        for row in rows:
            period = f"{row.period_month}/{row.period_year}"
            if row.credit_notes.filter(status=CreditStatus.ISSUED, vat_amount__gt=0).exists():
                self.stdout.write(f"  {period}: SKIPPED — a VAT credit note is already issued against it")
                continue
            self.stdout.write(f"  {period}: VAT {row.expected_vat:,.2f} -> 0")
            cleared += row.expected_vat
            row.expected_vat = ZERO
            row.save(update_fields=["expected_vat", "updated_at"])
            _update_arrears(tenant, row.period_month, row.period_year)
        return cleared
