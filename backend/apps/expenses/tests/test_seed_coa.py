"""
Tests for the seed_coa management command (Barclay F1 · Chart of Accounts).

Acceptance criteria:
  - every account in the COA document is present with correct code/name/type
  - running the seed twice is idempotent
  - entries that carry no COA code are surfaced (they would never post to the GL)
"""
from io import StringIO

import pytest
from django.core.management import call_command

from apps.expenses.coa import ACCOUNTS, CHART_CODES, HEADERS
from apps.expenses.models import Account, ExpenseCategory


def _run(*args):
    out = StringIO()
    call_command("seed_coa", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestSeedCoa:
    def test_seeds_the_full_chart(self):
        # The migration already seeded it; wipe and re-seed from scratch.
        ExpenseCategory.objects.update(account=None)
        Account.objects.all().delete()
        _run()
        assert set(Account.objects.values_list("code", flat=True)) == CHART_CODES
        assert Account.objects.count() == len(HEADERS) + len(ACCOUNTS)

    def test_accounts_have_correct_name_and_type(self):
        _run()
        for code, name, account_type, _parent, _desc in ACCOUNTS:
            acct = Account.objects.get(code=code)
            assert acct.name == name
            assert acct.account_type == account_type
            assert acct.is_header is False
        for code, name, account_type, _parent, _is_header, _desc in HEADERS:
            acct = Account.objects.get(code=code)
            assert acct.name == name
            assert acct.account_type == account_type
            assert acct.is_header is True

    def test_running_twice_is_idempotent(self):
        _run()
        out = _run()
        assert "0 created, 0 updated" in out
        assert Account.objects.count() == len(CHART_CODES)

    def test_repairs_a_drifted_account(self):
        acct = Account.objects.get(code="2600")
        acct.name = "WRONG NAME"
        acct.save(update_fields=["name"])
        out = _run()
        acct.refresh_from_db()
        assert acct.name == "VAT Payable"
        assert "1 updated" in out or "~ 2600" in out

    def test_dry_run_writes_nothing(self):
        Account.objects.filter(code="2600").delete()
        out = _run("--dry-run")
        assert "DRY RUN" in out
        assert not Account.objects.filter(code="2600").exists()

    def test_audit_flags_category_without_gl_account(self):
        ExpenseCategory.objects.create(name="Unmapped", account=None)
        out = _run("--audit")
        assert "NO GL account" in out
        assert "Unmapped" in out
