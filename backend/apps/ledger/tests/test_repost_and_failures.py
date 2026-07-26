"""
Tests for ledger re-post-on-edit (F3) and durable posting failures (F2).

- Editing a Payment / revising a UtilityCharge must update the general ledger,
  not leave it stuck at the original figure.
- A posting failure must be captured in PostingFailure (source still commits),
  and be replayable by `retry_posting_failures`.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, Unit, UnitClassification, UnitStatus
from apps.ledger.models import JournalEntry, PostingFailure
from apps.payments.models import Payment, PaymentSource, PaymentType, UtilityCharge
from apps.tenants.models import Tenant, TenantStatus

RESIDENTIAL_INCOME = "4110"
RENT_RECEIVABLE = "1040"
SERVICE_CHARGE_UTILITIES = "4150"


def _residential_tenant():
    building = Building.objects.create(name="Repost Block", code="RPB", total_floors=1)
    unit = Unit.objects.create(
        building=building, label="RPB1", monthly_rent=Decimal("20000"),
        classification=UnitClassification.RESIDENTIAL, status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Re", last_name="Post", id_number="RP001",
        phone="+254700000700", unit=unit, monthly_rent=Decimal("20000"),
        move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
    )


def _normal_entry(source_type, source_id):
    return JournalEntry.objects.get(
        source_type=source_type, source_id=source_id, kind="normal"
    )


def _credit_of(entry, code):
    line = entry.lines.get(account__code=code)
    return line.credit


def _debit_of(entry, code):
    line = entry.lines.get(account__code=code)
    return line.debit


@pytest.mark.django_db
class TestRepostOnEdit:
    def test_editing_payment_amount_updates_the_ledger(self):
        tenant = _residential_tenant()
        pmt = Payment.objects.create(
            tenant=tenant, amount=Decimal("20000.00"), payment_date="2026-06-05",
            period_month=6, period_year=2026, source=PaymentSource.MPESA,
            payment_type=PaymentType.RENT, reference="RP-1",
        )
        entry = _normal_entry("payment", pmt.pk)
        assert _credit_of(entry, RESIDENTIAL_INCOME) == Decimal("20000.00")

        # Correct a mis-keyed amount.
        pmt.amount = Decimal("15000.00")
        pmt.save()

        # Same single entry, rebuilt to the new figure — no duplicate.
        assert JournalEntry.objects.filter(
            source_type="payment", source_id=pmt.pk, kind="normal"
        ).count() == 1
        entry.refresh_from_db()
        assert _credit_of(entry, RESIDENTIAL_INCOME) == Decimal("15000.00")
        assert _debit_of(entry, "1020") == Decimal("15000.00")

    def test_revising_utility_charge_updates_the_ledger(self):
        tenant = _residential_tenant()
        charge = UtilityCharge.objects.create(
            tenant=tenant, posting_date="2026-06-05", period_month=6, period_year=2026,
            label="Water Usage", amount=Decimal("9000.00"),  # fat-fingered reading
        )
        entry = _normal_entry("utility_charge", charge.pk)
        assert _debit_of(entry, RENT_RECEIVABLE) == Decimal("9000.00")
        assert _credit_of(entry, SERVICE_CHARGE_UTILITIES) == Decimal("9000.00")

        # Corrected reading.
        charge.amount = Decimal("900.00")
        charge.save()

        entry.refresh_from_db()
        assert _debit_of(entry, RENT_RECEIVABLE) == Decimal("900.00")
        assert _credit_of(entry, SERVICE_CHARGE_UTILITIES) == Decimal("900.00")


@pytest.mark.django_db
class TestDurablePostingFailure:
    def test_failure_is_recorded_and_source_still_commits(self):
        tenant = _residential_tenant()
        with patch("apps.ledger.posting.post_payment", side_effect=RuntimeError("boom")):
            pmt = Payment.objects.create(
                tenant=tenant, amount=Decimal("20000.00"), payment_date="2026-06-05",
                period_month=6, period_year=2026, source=PaymentSource.MPESA,
                payment_type=PaymentType.RENT, reference="FAIL-1",
            )

        # Source row committed despite the GL failure...
        assert Payment.objects.filter(pk=pmt.pk).exists()
        # ...no journal entry was written...
        assert not JournalEntry.objects.filter(source_type="payment", source_id=pmt.pk).exists()
        # ...but the failure is captured durably, not swallowed.
        failure = PostingFailure.objects.get(source_type="payment", source_id=pmt.pk)
        assert failure.resolved is False
        assert "boom" in failure.error

    def test_retry_command_replays_and_resolves(self):
        tenant = _residential_tenant()
        with patch("apps.ledger.posting.post_payment", side_effect=RuntimeError("boom")):
            pmt = Payment.objects.create(
                tenant=tenant, amount=Decimal("20000.00"), payment_date="2026-06-05",
                period_month=6, period_year=2026, source=PaymentSource.MPESA,
                payment_type=PaymentType.RENT, reference="FAIL-2",
            )
        assert PostingFailure.objects.filter(source_id=pmt.pk, resolved=False).exists()

        # With posting healthy again, the retry command reconciles the books.
        call_command("retry_posting_failures")

        entry = _normal_entry("payment", pmt.pk)
        assert _credit_of(entry, RESIDENTIAL_INCOME) == Decimal("20000.00")
        failure = PostingFailure.objects.get(source_id=pmt.pk)
        assert failure.resolved is True
        assert failure.resolved_at is not None

    def test_successful_post_resolves_a_prior_failure_on_edit(self):
        tenant = _residential_tenant()
        with patch("apps.ledger.posting.post_payment", side_effect=RuntimeError("boom")):
            pmt = Payment.objects.create(
                tenant=tenant, amount=Decimal("20000.00"), payment_date="2026-06-05",
                period_month=6, period_year=2026, source=PaymentSource.MPESA,
                payment_type=PaymentType.RENT, reference="FAIL-3",
            )
        assert PostingFailure.objects.get(source_id=pmt.pk).resolved is False

        # A later successful save (edit) posts and clears the open failure.
        pmt.amount = Decimal("18000.00")
        pmt.save()

        assert PostingFailure.objects.get(source_id=pmt.pk).resolved is True
        assert _credit_of(_normal_entry("payment", pmt.pk), RESIDENTIAL_INCOME) == Decimal("18000.00")


@pytest.mark.django_db
def test_no_open_failures_is_a_noop():
    # Command runs cleanly with nothing to do.
    call_command("retry_posting_failures")
    assert PostingFailure.objects.filter(resolved=False).count() == 0
