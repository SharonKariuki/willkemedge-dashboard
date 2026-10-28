"""Automatic audit rows for changes to the records that matter.

`audit.record()` is called by hand where an action has a name and a reason
("voided payment — duplicate"). That covers the money paths, but most edits
(a unit's rent, a tenant's phone number, a building's paybill, an expense
amount) went through generic views and left no trace at all. Rather than
remember to instrument every one of them, the models below are watched: every
create, update and delete writes a CHANGE row with the fields that moved, from
the dashboard, the admin, a bank notification or a server command alike.

When a request also wrote a named EVENT, the Activity page folds these CHANGE
rows under it (they share a request_id), so the director reads one line with
the detail underneath rather than the same thing twice.

Not seen here: `QuerySet.update()` and `bulk_create()` bypass model signals.
Nothing in the request paths uses them on these models today; a management
command that does is still announced by its `command.run` row.

Deliberately not watched:
  * TenantCredit, CreditApplication, Refund — every write already records a
    named event in `payments.credits`.
  * Arrears creation and allocation — the monthly billing run and every
    payment rewrite them; the run records one summary event instead.
  * Unit.status — derived from payments and recalculated nightly. A manual
    status change records its own event in the unit view.
  * Ledger journal entries — derived from the records watched here.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from django.apps import apps as django_apps
from django.db.models.signals import post_delete, post_save, pre_save

from . import audit

logger = logging.getLogger(__name__)

ALWAYS_IGNORED = frozenset({"id", "created_at", "updated_at", "uploaded_at", "last_login"})


@dataclass(frozen=True)
class Tracked:
    model: str                              # "app_label.ModelName"
    object_type: str                        # stored on the row, e.g. "unit"
    noun: str                               # used in summaries, e.g. "unit"
    label: Callable[[object], str]          # what the object is called, e.g. "MCF01"
    ops: frozenset = frozenset({"create", "update", "delete"})
    #: Only these fields are compared. None means every concrete field.
    fields: tuple | None = None
    ignore: frozenset = frozenset()
    #: Shown as "changed", never the value (passwords).
    secret: frozenset = frozenset()
    #: Shown with all but the last three characters hidden (ID numbers).
    masked: frozenset = frozenset()
    #: A change to any of these marks the row financial. "*" means always.
    financial: frozenset = frozenset()
    #: Fields worth naming in the one-line summary of a new record.
    create_summary: tuple = ()


def _safe(fn):
    def wrapped(obj):
        try:
            return fn(obj)
        except Exception:  # noqa: BLE001 — a related row may already be gone on delete
            return f"#{obj.pk}"
    return wrapped


def _tenant_name(t) -> str:
    return f"{t.first_name} {t.last_name}".strip()


def _tenant_with_unit(t) -> str:
    return f"{_tenant_name(t)} ({t.unit.label})"


def _money(v) -> str:
    return f"KES {Decimal(v):,.2f}"


TENANT_MONEY = frozenset({
    "monthly_rent", "deposit_paid", "agreed_deposit", "is_billable", "due_day",
    "first_rent_month", "deposit_refund_percentage", "deposit_refund_amount",
})

TRACKED = [
    Tracked(
        "tenants.Tenant", "tenant", "tenant", _safe(_tenant_with_unit),
        masked=frozenset({"id_number", "kra_pin"}),
        financial=TENANT_MONEY,
        create_summary=("unit", "monthly_rent", "move_in_date"),
    ),
    Tracked(
        "tenants.TenantDocument", "tenant_document", "document",
        _safe(lambda d: f"{d.get_doc_type_display()} for {_tenant_name(d.tenant)}"),
        ops=frozenset({"create", "delete"}),
        fields=("doc_type", "original_name"),
    ),
    Tracked(
        "buildings.Building", "building", "building", _safe(lambda b: b.name),
        # The cover photo is image bytes: log that it changed, never the bytes.
        secret=frozenset({"photo"}),
        ignore=frozenset({"photo_content_type", "photo_updated_at"}),
        financial=frozenset({
            "water_rate_per_unit", "paybill_number", "paybill_account_format",
            "bank_name", "bank_branch", "bank_account", "bank_account_name",
        }),
    ),
    Tracked(
        "buildings.Unit", "unit", "unit", _safe(lambda u: u.label),
        ignore=frozenset({"status"}),
        financial=frozenset({"monthly_rent"}),
        create_summary=("building", "monthly_rent"),
    ),
    Tracked(
        "buildings.UnitAlias", "unit_alias", "payment alias",
        _safe(lambda a: f"{a.label} → {a.unit.label}"),
        ops=frozenset({"create", "delete"}),
    ),
    Tracked(
        "buildings.MaintenanceRequest", "maintenance", "maintenance request",
        _safe(lambda m: f"{m.unit.label}: {m.description[:60]}"),
        financial=frozenset({"cost"}),
        create_summary=("cost",),
    ),
    Tracked(
        "expenses.Expense", "expense", "expense",
        _safe(lambda e: f"{e.description[:60]} ({_money(e.amount)})"),
        financial=frozenset({"*"}),
        create_summary=("category", "building", "date"),
    ),
    Tracked(
        "expenses.ManualIncome", "manual_income", "income",
        _safe(lambda i: f"{i.description[:60]} ({_money(i.amount)})"),
        financial=frozenset({"*"}),
        create_summary=("account", "building", "date"),
    ),
    Tracked(
        "expenses.Account", "account", "ledger account", _safe(lambda a: f"{a.code} {a.name}"),
        financial=frozenset({"*"}),
    ),
    Tracked(
        "expenses.ExpenseCategory", "expense_category", "expense category",
        _safe(lambda c: c.name),
        financial=frozenset({"account"}),
    ),
    Tracked(
        "payments.Payment", "payment", "payment",
        _safe(lambda p: f"{_money(p.amount)} from {_tenant_with_unit(p.tenant)}"),
        ignore=frozenset({"idempotency_key"}),
        financial=frozenset({"*"}),
        create_summary=("source", "payment_type", "reference"),
    ),
    Tracked(
        "payments.UtilityCharge", "utility_charge", "charge",
        _safe(lambda c: f"{c.label} {c.period_month}/{c.period_year} for {_tenant_with_unit(c.tenant)}"),
        financial=frozenset({"*"}),
        create_summary=("amount", "units", "charge_type"),
    ),
    Tracked(
        "payments.Arrears", "arrears", "rent charge",
        _safe(lambda a: f"{a.period_month}/{a.period_year} for {_tenant_with_unit(a.tenant)}"),
        ops=frozenset({"update", "delete"}),
        fields=("expected_rent", "expected_vat", "period_month", "period_year"),
        financial=frozenset({"*"}),
    ),
    Tracked(
        "accounts.User", "user", "user account", _safe(lambda u: u.email),
        fields=("email", "first_name", "last_name", "role", "is_active", "is_staff",
                "is_superuser", "password"),
        secret=frozenset({"password"}),
    ),
]


# ── value formatting ─────────────────────────────────────────────────────────

def _fields(spec: Tracked, model) -> list:
    concrete = [f for f in model._meta.concrete_fields]
    if spec.fields is not None:
        wanted = set(spec.fields)
        concrete = [f for f in concrete if f.name in wanted]
    return [f for f in concrete if f.name not in ALWAYS_IGNORED and f.name not in spec.ignore]


def _mask(value) -> str:
    text = str(value or "")
    return text if len(text) <= 3 else "•" * (len(text) - 3) + text[-3:]


def _stored(spec: Tracked, f, value):
    """The value as kept in old_values/new_values."""
    if f.name in spec.secret:
        return "(hidden)"
    if f.name in spec.masked:
        return _mask(value)
    return audit._jsonable(value)


def _display(spec: Tracked, f, value) -> str:
    """The value as a person reads it in the summary line."""
    if f.name in spec.secret:
        return "(hidden)"
    if value is None or value == "":
        return "—"
    if f.name in spec.masked:
        return _mask(value)
    if f.is_relation:
        related = f.related_model._base_manager.filter(pk=value).first()
        return str(related) if related else f"#{value}"
    if f.choices:
        return str(dict(f.flatchoices).get(value, value))
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    if hasattr(value, "strftime") and not hasattr(value, "hour"):
        return value.strftime("%d/%m/%Y")
    text = str(value)
    return text if len(text) <= 40 else text[:39] + "…"


def _is_financial(spec: Tracked, changed: list[str]) -> bool:
    if "*" in spec.financial:
        return True
    return any(name in spec.financial for name in changed)


def _differs(f, old, new) -> bool:
    """Compare as the database would store them: "22000" and 22000.00 are equal."""
    try:
        return f.to_python(old) != f.to_python(new)
    except Exception:  # noqa: BLE001 — an unparseable value is a change by definition
        return old != new


def _verbose(f) -> str:
    return str(f.verbose_name).capitalize()


# ── signal handlers ──────────────────────────────────────────────────────────

_SPECS: dict[type, Tracked] = {}


def _on_pre_save(sender, instance, raw=False, update_fields=None, **_):
    spec = _SPECS.get(sender)
    if spec is None or raw or instance.pk is None or instance._state.adding:
        return
    try:
        fields = _fields(spec, sender)
        if update_fields is not None:
            fields = [f for f in fields if f.name in update_fields or f.attname in update_fields]
        if not fields:
            return
        old = sender._base_manager.filter(pk=instance.pk).values(*[f.attname for f in fields]).first()
        instance._audit_before = old
    except Exception:  # noqa: BLE001
        logger.exception("audit: could not read %s#%s before save", sender.__name__, instance.pk)


def _on_post_save(sender, instance, created=False, raw=False, **_):
    spec = _SPECS.get(sender)
    if spec is None or raw:
        return
    try:
        if created:
            _record_create(spec, sender, instance)
        else:
            before = instance.__dict__.pop("_audit_before", None)
            if before is not None:
                _record_update(spec, sender, instance, before)
    except Exception:  # noqa: BLE001 — auditing must not break the save
        logger.exception("audit: could not record save of %s#%s", sender.__name__, instance.pk)


def _on_post_delete(sender, instance, **_):
    spec = _SPECS.get(sender)
    if spec is None or "delete" not in spec.ops:
        return
    try:
        fields = _fields(spec, sender)
        label = spec.label(instance)
        audit.record(
            kind="change",
            action=f"{spec.object_type}.delete",
            object_type=spec.object_type,
            object_id=instance.pk,
            object_label=label,
            summary=f"Deleted {spec.noun} {label}",
            old_values={f.attname: _stored(spec, f, getattr(instance, f.attname)) for f in fields},
            is_financial=_is_financial(spec, [f.name for f in fields]),
        )
    except Exception:  # noqa: BLE001
        logger.exception("audit: could not record delete of %s#%s", sender.__name__, instance.pk)


def _record_create(spec: Tracked, model, instance) -> None:
    if "create" not in spec.ops:
        return
    fields = _fields(spec, model)
    by_name = {f.name: f for f in fields}
    label = spec.label(instance)
    details = [
        f"{_verbose(by_name[n])}: {_display(spec, by_name[n], getattr(instance, by_name[n].attname))}"
        for n in spec.create_summary if n in by_name
    ]
    summary = f"Added {spec.noun} {label}" + (f" — {'; '.join(details)}" if details else "")
    audit.record(
        kind="change",
        action=f"{spec.object_type}.create",
        object_type=spec.object_type,
        object_id=instance.pk,
        object_label=label,
        summary=summary,
        new_values={f.attname: _stored(spec, f, getattr(instance, f.attname)) for f in fields},
        is_financial=_is_financial(spec, list(spec.create_summary)),
    )


def _record_update(spec: Tracked, model, instance, before: dict) -> None:
    if "update" not in spec.ops:
        return
    changed = [
        f for f in _fields(spec, model)
        if f.attname in before and _differs(f, before[f.attname], getattr(instance, f.attname))
    ]
    if not changed:
        return
    label = spec.label(instance)
    parts = []
    for f in changed:
        if f.name in spec.secret:
            parts.append(f"{_verbose(f)} changed")
        else:
            old = _display(spec, f, before[f.attname])
            new = _display(spec, f, getattr(instance, f.attname))
            parts.append(f"{_verbose(f)}: {old} → {new}")
    audit.record(
        kind="change",
        action=f"{spec.object_type}.update",
        object_type=spec.object_type,
        object_id=instance.pk,
        object_label=label,
        summary=f"Changed {spec.noun} {label} — {'; '.join(parts)}",
        old_values={f.attname: _stored(spec, f, before[f.attname]) for f in changed},
        new_values={f.attname: _stored(spec, f, getattr(instance, f.attname)) for f in changed},
        is_financial=_is_financial(spec, [f.name for f in changed]),
    )


def connect() -> None:
    """Watch every model in TRACKED. Called once from AccountsConfig.ready()."""
    for spec in TRACKED:
        model = django_apps.get_model(spec.model)
        _SPECS[model] = spec
        uid = f"audit:{spec.model}"
        pre_save.connect(_on_pre_save, sender=model, dispatch_uid=uid + ":pre")
        post_save.connect(_on_post_save, sender=model, dispatch_uid=uid + ":post")
        post_delete.connect(_on_post_delete, sender=model, dispatch_uid=uid + ":delete")
