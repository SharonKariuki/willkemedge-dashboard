"""
Restate the general ledger from the records it is built from.

The journal is derived data: every entry is generated from a Payment, Arrears
row, UtilityCharge, Expense, ManualIncome, TenantCredit or Refund. When the
posting rules change (as they did on the move from cash to accrual basis) or an
entry drifted from its source, this brings every entry back in line with the
current rules. It is idempotent: a second run changes nothing.

What it does, in order:

  1. re-posts every source row's NORMAL entry (and the REVERSAL of every voided
     payment, voided credit or voided refund) under today's rules
  2. drops the legacy entry types the rules no longer produce — ``opening_ar``
     (the go-live balances the reconciled rent roll replaced; the opening rows
     now post themselves) and ``credit_application`` (applying a credit moves
     nothing under accrual)
  3. reverses entries whose source row was deleted without one, and drops
     reversals whose original entry no longer exists

Run it through ``manage.py rebuild_ledger`` (dry run unless ``--apply``).
"""
from __future__ import annotations

from collections import Counter

from django.db import transaction


def _mirror_entry(entry):
    """Post the mirror-image REVERSAL of an entry whose source row is gone."""
    from .posting import _build_entry, _mirror

    lines = [(ln.account.code, ln.debit, ln.credit, ln.description) for ln in entry.lines.all()]
    return _build_entry(
        date=entry.date,
        memo=f"REVERSAL: {entry.memo}"[:255],
        reference=entry.reference,
        building=entry.building,
        source_type=entry.source_type,
        source_id=entry.source_id,
        kind="reversal",
        lines=_mirror(lines),
    )


def _repost_reversal(source_type, source_id, fn):
    """Rebuild a REVERSAL under today's rules, keeping its original date."""
    from .models import JournalEntry

    old = JournalEntry.objects.filter(
        source_type=source_type, source_id=source_id, kind="reversal"
    ).first()
    on = old.date if old else None
    if old:
        old.delete()
    return fn(on)


def rebuild() -> Counter:
    """Restate the ledger. Returns a tally of what it did, for the command."""
    from apps.expenses.models import Expense, ManualIncome
    from apps.payments.models import (
        Arrears,
        CreditStatus,
        Payment,
        Refund,
        RefundStatus,
        TenantCredit,
        UtilityCharge,
    )

    from . import posting
    from .checks import orphan_entries
    from .models import JournalEntry

    done: Counter = Counter()

    with transaction.atomic():
        for p in Payment.objects.select_related("tenant__unit__building"):
            posting.post_payment(p, replace=True)
            done["payments"] += 1
            if p.voided_at:
                _repost_reversal("payment", p.pk, lambda _on, p=p: posting.reverse_payment(p))

        for a in Arrears.objects.select_related("tenant__unit__building"):
            if posting.post_arrear(a, replace=True):
                done["rent charges"] += 1

        for u in UtilityCharge.objects.select_related("tenant__unit__building"):
            posting.post_utility_charge(u, replace=True)
            done["water/other charges"] += 1

        for e in Expense.objects.select_related("category__account", "building", "unit"):
            if e.category_id and e.category.account_id:
                posting.post_expense(e, replace=True)
                done["expenses"] += 1

        for m in ManualIncome.objects.select_related("account", "building"):
            posting.post_manual_income(m, replace=True)
            done["manual income"] += 1

        for c in TenantCredit.objects.select_related("tenant__unit__building", "expense_category__account"):
            posting.post_tenant_credit(c, replace=True)
            done["credits"] += 1
            if c.status == CreditStatus.VOID:
                _repost_reversal(
                    "tenant_credit", c.pk,
                    lambda on, c=c: posting.reverse_tenant_credit(c, on=on or c.credit_date),
                )

        for r in Refund.objects.select_related("tenant__unit__building").prefetch_related("lines"):
            if not r.sent_on:
                continue  # never left the bank, never posted
            posting.post_refund(r, replace=True)
            done["refunds"] += 1
            if r.status == RefundStatus.VOID:
                _repost_reversal(
                    "tenant_refund", r.pk,
                    lambda on, r=r: posting.reverse_refund(r, on=on or r.sent_on),
                )

        for legacy in ("opening_ar", "credit_application"):
            stale = JournalEntry.objects.filter(source_type=legacy)
            if n := stale.count():
                stale.delete()
                done[f"legacy {legacy} entries dropped"] += n

        lone_normals, lone_reversals = orphan_entries()
        for entry in lone_normals:
            _mirror_entry(entry)
            done["deleted records reversed"] += 1
        for entry in lone_reversals:
            entry.delete()
            done["reversals without an original dropped"] += 1

    return done
