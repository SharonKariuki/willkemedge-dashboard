"""
Who the reminder crons would text, without texting anyone.

The two tenant-facing jobs -- `rent-reminders` (08:00 EAT) and
`arrears-reminders` (09:00 EAT) -- have never run in production: the workflow
that calls them exits early because CRON_TRIGGER_TOKEN was never set. Turning
them on therefore sends the first message every active tenant has ever had
from this system, and the arrears one quotes a figure and says "settle
immediately". That is worth looking at before it goes out, not after.

This mirrors the selection logic of both tasks exactly -- same due-day clamp,
same lead window, same current-period Arrears test, same dedupe key -- and
reports what they would do. It writes nothing and sends nothing.

Reminder day matters: rent reminders only fire inside the lead window before a
tenant's due day, so a run today and a run on the 3rd give different answers.
`--date` checks any day, and the wave table shows the whole month's shape.

Usage:
    python manage.py preview_reminders
    python manage.py preview_reminders --date 2026-09-03
    python manage.py preview_reminders --list
"""
import calendar
import datetime as dt
from collections import Counter, defaultdict
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

ZERO = Decimal("0.00")


class Command(BaseCommand):
    help = "Dry-run the rent and arrears reminder crons. Reads only; sends nothing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="Simulate a given day (YYYY-MM-DD). Defaults to today, Nairobi time.",
        )
        parser.add_argument(
            "--list", action="store_true",
            help="Name every tenant who would be messaged, not just the counts.",
        )

    def handle(self, *args, **options):
        from apps.payments.models import Arrears, TenantNotification
        from apps.tenants.models import Tenant, TenantStatus

        if options["date"]:
            try:
                today = dt.date.fromisoformat(options["date"])
            except ValueError as exc:
                raise CommandError("--date must be YYYY-MM-DD") from exc
        else:
            today = timezone.localdate()

        show_all = options["list"]
        lead_days = int(getattr(settings, "RENT_REMINDER_LEAD_DAYS", 3))
        last_day = calendar.monthrange(today.year, today.month)[1]

        active = list(
            Tenant.objects.filter(status=TenantStatus.ACTIVE)
            .select_related("unit", "unit__building")
        )

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nReminder preflight - {today} (lead {lead_days} days), "
            f"{len(active)} active tenant(s)"
        ))

        # Tenants the jobs silently skip. Worth seeing: a tenant with no phone
        # is never chased by SMS and nothing anywhere says so.
        no_unit = [t for t in active if not t.unit_id]
        no_phone = [t for t in active if t.unit_id and not t.phone]
        reachable = [t for t in active if t.unit_id and t.phone]

        # -- rent reminders ------------------------------------------------
        rent_due, rent_dedupe = [], []
        for tenant in reachable:
            due_day = min(int(tenant.due_day or 5), last_day)
            due_date = dt.date(today.year, today.month, due_day)
            if not 0 <= (due_date - today).days <= lead_days:
                continue
            key = f"rent_reminder:{tenant.id}:{due_date:%Y-%m}"
            if TenantNotification.objects.filter(dedupe_key=key).exists():
                rent_dedupe.append(tenant)
            else:
                rent_due.append(tenant)

        self.stdout.write(self.style.MIGRATE_HEADING("\nrent-reminders  (08:00 EAT)"))
        self.stdout.write(f"  would send             : {len(rent_due)}")
        self.stdout.write(
            f"  already sent this month: {len(rent_dedupe)} (deduped, would not resend)"
        )
        self._by_building(rent_due)
        if show_all:
            self._name_them(
                rent_due,
                lambda t: f"due {min(int(t.due_day or 5), last_day)}",
            )

        # -- arrears reminders ---------------------------------------------
        overdue, overdue_dedupe = [], []
        owed = {}
        owed_total = ZERO
        for tenant in reachable:
            due_day = min(int(tenant.due_day or 5), last_day)
            if today < dt.date(today.year, today.month, due_day):
                continue
            arrears = Arrears.objects.filter(
                tenant=tenant, period_month=today.month,
                period_year=today.year, is_cleared=False,
            ).first()
            if not arrears or arrears.balance <= 0:
                continue
            key = f"rent_overdue:{tenant.id}:{today.year}-{today.month:02d}"
            if TenantNotification.objects.filter(dedupe_key=key).exists():
                overdue_dedupe.append(tenant)
            else:
                overdue.append(tenant)
                owed[tenant.pk] = arrears.balance
                owed_total += arrears.balance

        self.stdout.write(self.style.MIGRATE_HEADING("\narrears-reminders  (09:00 EAT)"))
        self.stdout.write(f"  would send             : {len(overdue)}")
        self.stdout.write(
            f"  already sent this month: {len(overdue_dedupe)} (deduped, would not resend)"
        )
        self.stdout.write(f"  total quoted as owed   : KES {owed_total:,.2f}")
        if overdue:
            self.stdout.write(
                f"  largest single demand  : KES {max(owed.values()):,.2f}"
            )
            self.stdout.write(self.style.WARNING(
                "  ^ each of these is told to 'settle immediately'. Check the figures "
                "are ones you would stand behind before enabling."
            ))
        self._by_building(overdue)
        if show_all:
            self._name_them(overdue, lambda t: f"KES {owed[t.pk]:,.0f}")

        # -- the month's shape ----------------------------------------------
        # A single day's count understates the wave: reminders fire per tenant
        # on their own due day, so the month lands in clusters.
        waves = Counter(min(int(t.due_day or 5), last_day) for t in reachable)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nRent-reminder waves across {today:%B %Y}"
        ))
        for day in sorted(waves):
            first_fire = max(1, day - lead_days)
            self.stdout.write(
                f"  due day {day:>2} : {waves[day]:>3} tenant(s), "
                f"messaged from the {first_fire}"
            )
        self.stdout.write(
            f"  -> {len(reachable)} rent reminder(s) per month in total, "
            "one per reachable tenant"
        )

        # -- silent skips ----------------------------------------------------
        if no_phone or no_unit:
            self.stdout.write(self.style.MIGRATE_HEADING("\nNever reached by either job"))
            if no_phone:
                self.stdout.write(self.style.WARNING(
                    f"  no phone number : {len(no_phone)}"
                ))
                for t in no_phone[:15]:
                    label = t.unit.label if t.unit_id else "-"
                    self.stdout.write(f"      {label:<8} {t.full_name}")
            if no_unit:
                self.stdout.write(self.style.WARNING(
                    f"  no unit assigned: {len(no_unit)}"
                ))

        self.stdout.write(self.style.SUCCESS(
            f"\nNothing was sent and nothing was written. "
            f"{len(rent_due) + len(overdue)} message(s) would go out on {today}."
        ))

    def _by_building(self, tenants):
        if not tenants:
            return
        grouped = defaultdict(int)
        for t in tenants:
            grouped[t.unit.building.name if t.unit_id else "-"] += 1
        for name in sorted(grouped):
            self.stdout.write(f"      {grouped[name]:>3}  {name}")

    def _name_them(self, tenants, note):
        for t in sorted(tenants, key=lambda x: (x.unit.building.name, x.unit.label)):
            self.stdout.write(
                f"      {t.unit.label:<8} {t.full_name:<30} {t.phone:<15} {note(t)}"
            )
