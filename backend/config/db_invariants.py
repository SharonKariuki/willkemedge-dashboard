"""Financial invariants that PostgreSQL should enforce, in one place.

Several rules the books depend on lived only in Python — in a serializer, or
implicitly in a service that happened to raise first. A serializer guards the
API; it does not guard a management command, a Django-admin save, a data
migration, or a psql session. For a system holding real money the database has
to be the last line, because it is the only layer every write passes through.

This module is the single definition of those rules. It is consumed by:

  * ``config/../apps/*/migrations/*`` — the migration that installs the CHECK
    constraints runs :func:`violations` first and refuses to proceed if live
    data does not already satisfy them (see the note below on why it refuses
    rather than repairs).
  * ``manage.py check_db_invariants`` — the same scan, on demand, so the
    operator can confirm production is clean BEFORE deploying the migration.

Why the migration refuses instead of healing
--------------------------------------------
``0018_arrears_check_constraints`` established the "heal, then constrain"
pattern for a balance that was safe to clamp. These rules are different: every
one of them guards an AMOUNT or a PERIOD on a financial record. Silently
rewriting a payment's value, or the month it belongs to, is restating the books
— exactly what a migration must never do unattended. So the migration stops and
names the offending rows, the operator decides, and the deploy is retried.

A failed migration is a safe failure here: ``build.sh`` runs under
``set -o errexit``, so the release aborts and Render keeps serving the previous
deploy. Nothing goes down.

NOTE on importing this from a migration: migrations are normally self-contained
because app code drifts. What is imported here is a declarative spec resolved
through the historical model registry (``apps.get_model``), not live model
behaviour, so drift can only change which rows a *pre-flight* reports — never
what the migration does to the schema.
"""

#: (app_label, model, human label, ORM filter selecting VIOLATING rows, rule text)
INVARIANTS = [
    # ── Money must be positive where a negative or zero is meaningless ──────
    # Payment: every write path routes through `split_tax_inclusive`, which
    # already rejects <= 0, and migration 0017 removed the legacy negative
    # "VOID:" rows. This makes that guarantee structural.
    ("payments", "Payment", "payment amount",
     {"amount__lte": 0}, "Payment.amount must be greater than 0"),
    ("expenses", "Expense", "expense amount",
     {"amount__lte": 0}, "Expense.amount must be greater than 0"),
    ("expenses", "ManualIncome", "manual income amount",
     {"amount__lte": 0}, "ManualIncome.amount must be greater than 0"),
    # UtilityCharge is deliberately ABSENT from the amount rules: a negative
    # utility charge is a credit note, and `ledger.posting.post_utility_charge`
    # has an explicit branch that books one. Constraining it would break a
    # supported operation.

    # ── Periods must name a real month ─────────────────────────────────────
    # Arrears already has this (0018). A payment or expense filed to month 13
    # vanishes from every period-keyed report and reconciles against nothing.
    ("payments", "Payment", "payment period month",
     {"period_month__lt": 1}, "Payment.period_month must be 1-12"),
    ("payments", "Payment", "payment period month",
     {"period_month__gt": 12}, "Payment.period_month must be 1-12"),
    ("payments", "UtilityCharge", "utility charge period month",
     {"period_month__lt": 1}, "UtilityCharge.period_month must be 1-12"),
    ("payments", "UtilityCharge", "utility charge period month",
     {"period_month__gt": 12}, "UtilityCharge.period_month must be 1-12"),
    ("expenses", "Expense", "expense period month",
     {"period_month__lt": 1}, "Expense.period_month must be 1-12"),
    ("expenses", "Expense", "expense period month",
     {"period_month__gt": 12}, "Expense.period_month must be 1-12"),
    ("expenses", "ManualIncome", "manual income period month",
     {"period_month__lt": 1}, "ManualIncome.period_month must be 1-12"),
    ("expenses", "ManualIncome", "manual income period month",
     {"period_month__gt": 12}, "ManualIncome.period_month must be 1-12"),

    # ── Rents and deposits cannot be negative ──────────────────────────────
    # `adjust-rent` used float arithmetic across every unit in a building and
    # had no lower bound; a negative rent inverts every obligation derived
    # from it.
    ("buildings", "Unit", "unit rent",
     {"monthly_rent__lt": 0}, "Unit.monthly_rent must be >= 0"),
    ("tenants", "Tenant", "tenant rent",
     {"monthly_rent__lt": 0}, "Tenant.monthly_rent must be >= 0"),
    ("tenants", "Tenant", "tenant deposit",
     {"deposit_paid__lt": 0}, "Tenant.deposit_paid must be >= 0"),

    # ── Due day must be a day of the month ─────────────────────────────────
    # `send_rent_reminders` builds date(year, month, due_day). A zero raises
    # ValueError and takes the whole reminder run down for every tenant.
    ("tenants", "Tenant", "tenant due day",
     {"due_day__lt": 1}, "Tenant.due_day must be 1-31"),
    ("tenants", "Tenant", "tenant due day",
     {"due_day__gt": 31}, "Tenant.due_day must be 1-31"),

    # ── Deposit refund percentage is a percentage ──────────────────────────
    # The move-out view multiplies deposit_paid by this.
    ("tenants", "Tenant", "deposit refund percentage",
     {"deposit_refund_percentage__lt": 0},
     "Tenant.deposit_refund_percentage must be 0-100"),
    ("tenants", "Tenant", "deposit refund percentage",
     {"deposit_refund_percentage__gt": 100},
     "Tenant.deposit_refund_percentage must be 0-100"),
]


def violations(apps, *, limit: int = 10) -> list[dict]:
    """Return one entry per broken invariant, with a sample of offending ids.

    ``apps`` is a model registry — the historical one inside a migration, or
    ``django.apps.apps`` from the management command.
    """
    found = []
    for app_label, model_name, label, lookup, rule in INVARIANTS:
        model = apps.get_model(app_label, model_name)
        qs = model.objects.filter(**lookup)
        count = qs.count()
        if count:
            found.append({
                "model": f"{app_label}.{model_name}",
                "label": label,
                "rule": rule,
                "count": count,
                "sample_ids": list(qs.values_list("pk", flat=True)[:limit]),
            })
    return found


def duplicate_utility_charges(apps, *, limit: int = 10) -> list[dict]:
    """Rows that block the (tenant, period, label) uniqueness on UtilityCharge.

    Both writers — the staff meter form and the spreadsheet importer — use
    ``update_or_create`` on exactly these four fields, so uniqueness is already
    the intent. Without the constraint two concurrent submissions both find
    nothing and both insert, double-billing the tenant for the same water.
    """
    from django.db.models import Count

    UtilityCharge = apps.get_model("payments", "UtilityCharge")
    dupes = (
        UtilityCharge.objects.values("tenant_id", "period_year", "period_month", "label")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .order_by("-n")[:limit]
    )
    return [dict(row) for row in dupes]


def format_report(broken: list[dict], dupes: list[dict]) -> str:
    """Human-readable summary used by both the command and the migration error."""
    lines = []
    for item in broken:
        lines.append(
            f"  · {item['model']}: {item['count']} row(s) break \"{item['rule']}\" "
            f"(ids: {', '.join(str(i) for i in item['sample_ids'])}"
            f"{'…' if item['count'] > len(item['sample_ids']) else ''})"
        )
    for row in dupes:
        lines.append(
            f"  · payments.UtilityCharge: {row['n']} duplicate charges for "
            f"tenant {row['tenant_id']} {row['period_month']}/{row['period_year']} "
            f"\"{row['label']}\""
        )
    return "\n".join(lines)
