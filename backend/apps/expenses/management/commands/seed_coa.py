"""
Seed / verify the Chart of Accounts.

The chart was first installed by migration 0005, but a migration only runs
once. This command lets ops re-seed or verify the COA on an existing database
(after a manual edit, a partial restore, or a chart revision) without replaying
migrations.

It is idempotent: running it twice makes no further changes.

    python manage.py seed_coa               # seed / repair the chart
    python manage.py seed_coa --dry-run     # report what would change
    python manage.py seed_coa --audit       # chart + data-integrity report only

The audit reports entries that would not post to the ledger because they carry
no COA code — expense categories with no account, and expenses whose category
is unmapped.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.expenses.coa import (
    ACCOUNTS,
    CHART_CODES,
    EXPENSE_CATEGORIES,
    HEADERS,
    LEGACY_CATEGORY_TO_CODE,
)


class Command(BaseCommand):
    help = "Seed or verify the Chart of Accounts (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change, then roll back.")
        parser.add_argument("--audit", action="store_true",
                            help="Only report chart + data-integrity gaps; make no changes.")

    def handle(self, *args, **opts):
        from apps.expenses.models import Account, Expense, ExpenseCategory

        if opts["audit"]:
            self._audit(Account, ExpenseCategory, Expense)
            return

        created = updated = unchanged = 0
        rows = (
            [(c, n, t, p, True, d) for c, n, t, p, _h, d in HEADERS]
            + [(c, n, t, p, False, d) for c, n, t, p, d in ACCOUNTS]
        )

        with transaction.atomic():
            for code, name, account_type, parent_code, is_header, description in rows:
                defaults = {
                    "name": name,
                    "account_type": account_type,
                    "parent_code": parent_code,
                    "is_header": is_header,
                    "description": description,
                    "is_active": True,
                }
                existing = Account.objects.filter(code=code).first()
                if existing is None:
                    Account.objects.create(code=code, **defaults)
                    created += 1
                    self.stdout.write(f"  + {code} {name}")
                elif any(getattr(existing, f) != v for f, v in defaults.items()):
                    for field, value in defaults.items():
                        setattr(existing, field, value)
                    existing.save(update_fields=list(defaults))
                    updated += 1
                    self.stdout.write(f"  ~ {code} {name}")
                else:
                    unchanged += 1

            cat_created, cat_repaired = self._seed_categories(Account, ExpenseCategory)

            if opts["dry_run"]:
                transaction.set_rollback(True)

        if cat_created or cat_repaired:
            self.stdout.write(
                f"\nCategories: {cat_created} created, {cat_repaired} legacy row(s) bound to a GL code."
            )

        summary = f"\n{created} created, {updated} updated, {unchanged} unchanged."
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING(summary + "  [DRY RUN — rolled back]"))
        else:
            self.stdout.write(self.style.SUCCESS(summary))

        self._audit(Account, ExpenseCategory, Expense)

    # ── categories ───────────────────────────────────────────────────────────

    def _seed_categories(self, Account, ExpenseCategory):
        """Seed the locked category set and bind any legacy uncoded rows.

        Every category must map to a GL code — an unmapped one silently drops
        its expenses from the ledger.
        """
        by_code = {a.code: a for a in Account.objects.all()}
        created = repaired = 0

        for name, code in EXPENSE_CATEGORIES:
            account = by_code.get(code)
            if account is None:
                continue
            _cat, was_created = ExpenseCategory.objects.update_or_create(
                name=name, defaults={"account": account},
            )
            if was_created:
                created += 1
                self.stdout.write(f"  + category {name} → {code}")

        for cat in ExpenseCategory.objects.filter(account__isnull=True):
            code = LEGACY_CATEGORY_TO_CODE.get(cat.name.strip().lower())
            account = by_code.get(code) if code else None
            if account is None:
                continue
            cat.account = account
            cat.save(update_fields=["account"])
            repaired += 1
            self.stdout.write(f"  ~ category {cat.name} → {code} (was unmapped)")

        return created, repaired

    # ── audit ────────────────────────────────────────────────────────────────

    def _audit(self, Account, ExpenseCategory, Expense):
        self.stdout.write("\n-- Chart integrity --")

        missing = CHART_CODES - set(Account.objects.values_list("code", flat=True))
        if missing:
            self.stdout.write(self.style.ERROR(
                f"  {len(missing)} chart account(s) MISSING from the DB: {', '.join(sorted(missing))}"
            ))
        else:
            self.stdout.write(f"  All {len(CHART_CODES)} chart accounts present.")

        extras = [a for a in Account.objects.all() if a.code not in CHART_CODES]
        if extras:
            self.stdout.write(self.style.WARNING(
                f"  {len(extras)} account(s) NOT in the chart (left untouched — remove by hand "
                f"once you have confirmed they carry no journal lines): "
                + ", ".join(f"{a.code} {a.name}" for a in extras)
            ))

        self.stdout.write("\n-- Entries that would not post (no COA code) --")

        uncoded_cats = ExpenseCategory.objects.filter(account__isnull=True)
        if uncoded_cats.exists():
            self.stdout.write(self.style.WARNING(
                f"  {uncoded_cats.count()} expense category/ies have NO GL account: "
                + ", ".join(c.name for c in uncoded_cats)
            ))
            orphan_expenses = Expense.objects.filter(category__account__isnull=True).count()
            if orphan_expenses:
                self.stdout.write(self.style.ERROR(
                    f"  {orphan_expenses} expense(s) under those categories are SKIPPED by the ledger."
                ))
        else:
            self.stdout.write("  Every expense category maps to a GL account.")
