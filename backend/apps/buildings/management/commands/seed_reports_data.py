"""
Seed realistic mock data for the Reports page.

Creates tenants, payments, arrears, expense categories, and expenses spanning
the last N months so every Reports tab has something to render.

Usage:
    python manage.py seed_reports_data
    python manage.py seed_reports_data --flush        # wipe tenants/payments/arrears/expenses first
    python manage.py seed_reports_data --months 18
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.buildings.models import Building, Unit, UnitStatus
from apps.expenses.models import Expense, ExpenseCategory
from apps.payments.models import Arrears, Payment, PaymentSource
from apps.tenants.models import Tenant, TenantStatus

FIRST_NAMES = [
    "Amani", "Brian", "Catherine", "Daniel", "Esther", "Fatuma", "George",
    "Hannah", "Ibrahim", "Joyce", "Kevin", "Linda", "Mary", "Nicholas",
    "Olivia", "Peter", "Rose", "Samuel", "Teresa", "Vincent", "Wambui",
    "Yvonne", "Zawadi",
]
LAST_NAMES = [
    "Odhiambo", "Mwangi", "Kariuki", "Otieno", "Wanjiku", "Kimani",
    "Njoroge", "Achieng", "Kibet", "Omondi", "Akinyi", "Chepkoech",
    "Wekesa", "Mutua", "Nyambura", "Korir",
]

EXPENSE_CATEGORIES = [
    "Maintenance", "Utilities", "Security", "Cleaning", "Repairs",
    "Water", "Electricity", "Garbage Collection", "Management Fee",
]

EXPENSE_DESCRIPTIONS = {
    "Maintenance": ["General upkeep", "Plumbing check", "Painting touch-up"],
    "Utilities": ["Common-area lights", "Water pump service", "Generator fuel"],
    "Security": ["Guard salary", "CCTV maintenance", "Gate repair"],
    "Cleaning": ["Daily cleaning", "Deep clean corridors", "Window wash"],
    "Repairs": ["Roof patch", "Door replacement", "Tile repair"],
    "Water": ["Water bill", "Borehole service"],
    "Electricity": ["KPLC bill", "Transformer maintenance"],
    "Garbage Collection": ["Monthly garbage service"],
    "Management Fee": ["Property management retainer"],
}


def last_n_periods(end_year: int, end_month: int, count: int):
    """Return the last `count` (year, month) tuples ending at end_year/end_month, oldest first."""
    y, m = end_year, end_month
    out = []
    for _ in range(count):
        out.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


class Command(BaseCommand):
    help = "Seed tenants, payments, arrears, and expenses for the Reports page."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing tenants, payments, arrears, and expenses first.",
        )
        parser.add_argument(
            "--months",
            type=int,
            default=12,
            help="How many months of history to generate (default 12).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush"]:
            Payment.objects.all().delete()
            Arrears.objects.all().delete()
            Expense.objects.all().delete()
            Tenant.objects.all().delete()
            self.stdout.write(self.style.WARNING(
                "Flushed tenants, payments, arrears, and expenses."
            ))

        if Building.objects.count() == 0:
            self.stdout.write(self.style.ERROR(
                "No buildings found — run `python manage.py seed_dev_data` first."
            ))
            return

        random.seed(42)
        months = options["months"]
        today = timezone.now().date()
        periods = last_n_periods(today.year, today.month, months)

        tenants_by_unit = self._seed_tenants(today, months)
        self._seed_payments_and_arrears(tenants_by_unit, periods, today)
        self._seed_expenses(periods)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {Tenant.objects.count()} tenants · "
            f"{Payment.objects.count()} payments · "
            f"{Arrears.objects.count()} arrears · "
            f"{Expense.objects.count()} expenses."
        ))

    # ────────────────────────────────────────────────────────────────────────
    def _seed_tenants(self, today, months):
        tenants_by_unit: dict[int, Tenant] = {}

        occupied = list(
            Unit.objects.exclude(status=UnitStatus.VACANT).select_related("building")
        )
        # Fill a few vacant units and mark them moved-out to populate the move log.
        extras = list(
            Unit.objects.filter(status=UnitStatus.VACANT)
            .select_related("building")
            .order_by("id")[:3]
        )
        extra_ids = {u.id for u in extras}

        idx = 0
        for unit in occupied + extras:
            existing = Tenant.objects.filter(unit=unit).first()
            if existing:
                tenants_by_unit[unit.id] = existing
                continue

            fn = random.choice(FIRST_NAMES)
            ln = random.choice(LAST_NAMES)
            id_num = f"3{10000000 + idx:08d}"
            idx += 1

            move_in = today - timedelta(days=random.randint(60, max(60, months * 30)))
            if unit.id in extra_ids:
                status = TenantStatus.MOVED_OUT
                move_out = today - timedelta(days=random.randint(10, 50))
            else:
                status = TenantStatus.ACTIVE
                move_out = None

            tenant = Tenant.objects.create(
                first_name=fn,
                last_name=ln,
                id_number=id_num,
                phone=f"+2547{random.randint(10_000_000, 99_999_999)}",
                email=f"{fn.lower()}.{ln.lower()}{idx}@example.com",
                unit=unit,
                monthly_rent=unit.monthly_rent,
                deposit_paid=unit.monthly_rent,
                move_in_date=move_in,
                move_out_date=move_out,
                status=status,
            )
            tenants_by_unit[unit.id] = tenant

        return tenants_by_unit

    # ────────────────────────────────────────────────────────────────────────
    def _seed_payments_and_arrears(self, tenants_by_unit, periods, today):
        sources = [s.value for s in PaymentSource]

        for tenant in tenants_by_unit.values():
            unit = tenant.unit
            rent: Decimal = tenant.monthly_rent

            for y, m in periods:
                period_start = date(y, m, 1)
                if tenant.move_in_date and period_start < tenant.move_in_date.replace(day=1):
                    continue
                if tenant.move_out_date and period_start > tenant.move_out_date:
                    continue

                is_current = (y == today.year and m == today.month)

                if is_current:
                    behaviour = {
                        UnitStatus.OCCUPIED_PAID: "paid",
                        UnitStatus.OCCUPIED_PARTIAL: "partial",
                        UnitStatus.OCCUPIED_UNPAID: "unpaid",
                        UnitStatus.ARREARS: "unpaid",
                    }.get(unit.status, "paid")
                else:
                    behaviour = random.choices(
                        ["paid", "partial", "unpaid"],
                        weights=[78, 15, 7],
                    )[0]

                safe_day = min(28, random.randint(1, 10) if behaviour == "paid" else random.randint(5, 28))

                if behaviour == "paid":
                    Payment.objects.create(
                        tenant=tenant,
                        amount=rent,
                        payment_date=date(y, m, safe_day),
                        period_month=m,
                        period_year=y,
                        source=random.choice(sources),
                        reference=f"TRX{y}{m:02d}{tenant.id:04d}",
                    )
                elif behaviour == "partial":
                    ratio = Decimal(str(random.choice([0.4, 0.5, 0.6, 0.7])))
                    paid = (rent * ratio).quantize(Decimal("0.01"))
                    Payment.objects.create(
                        tenant=tenant,
                        amount=paid,
                        payment_date=date(y, m, safe_day),
                        period_month=m,
                        period_year=y,
                        source=random.choice(sources),
                        reference=f"TRX{y}{m:02d}{tenant.id:04d}",
                    )
                    cleared = False if is_current else random.random() < 0.55
                    Arrears.objects.create(
                        tenant=tenant,
                        period_month=m,
                        period_year=y,
                        expected_rent=rent,
                        amount_paid=paid,
                        balance=rent - paid,
                        is_cleared=cleared,
                    )
                else:  # unpaid
                    cleared = False if is_current else random.random() < 0.45
                    Arrears.objects.create(
                        tenant=tenant,
                        period_month=m,
                        period_year=y,
                        expected_rent=rent,
                        amount_paid=Decimal("0"),
                        balance=rent,
                        is_cleared=cleared,
                    )

    # ────────────────────────────────────────────────────────────────────────
    def _seed_expenses(self, periods):
        categories = {
            name: ExpenseCategory.objects.get_or_create(name=name)[0]
            for name in EXPENSE_CATEGORIES
        }
        buildings = list(Building.objects.all())
        amount_bands = [1500, 2500, 3500, 5000, 7500, 12000, 18000, 25000]

        for y, m in periods:
            n = random.randint(5, 8)
            for _ in range(n):
                cat_name = random.choice(EXPENSE_CATEGORIES)
                desc = random.choice(EXPENSE_DESCRIPTIONS[cat_name])
                building = random.choice(buildings + [None])  # some unscoped
                amount = Decimal(random.choice(amount_bands))
                Expense.objects.create(
                    date=date(y, m, random.randint(1, 28)),
                    building=building,
                    category=categories[cat_name],
                    amount=amount,
                    description=desc,
                    reference=f"EXP{y}{m:02d}-{random.randint(100, 999)}",
                    period_month=m,
                    period_year=y,
                )
