"""
Production runs Celery tasks inline (CELERY_TASK_ALWAYS_EAGER, no worker).
There, a task's `self.retry()` re-runs it on the spot and then raises out of
`.delay()`, so a failed receipt email turned recording a payment into a 500,
and the SMS that had already gone out was sent again on every re-run.

Inline, a failed notification is now logged once and given up on; with a
worker, the task still retries later as before.
"""
import datetime as _dt
from decimal import Decimal
from unittest import mock

import pytest
from celery.exceptions import Retry

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments import tasks
from apps.payments.models import Payment, PaymentSource, PaymentType
from apps.tenants.models import Tenant, TenantStatus


@pytest.fixture
def payment(db):
    building = Building.objects.create(name="Test Court", total_floors=1)
    unit = Unit.objects.create(
        building=building, label="TC01", monthly_rent=Decimal("9000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    tenant = Tenant.objects.create(
        first_name="Test", last_name="Tenant", id_number="TEST-TC01",
        phone="+254700000001", unit=unit, monthly_rent=Decimal("9000"),
        deposit_paid=Decimal("0"), move_in_date=_dt.date(2026, 6, 1),
        status=TenantStatus.ACTIVE,
    )
    return Payment.objects.create(
        tenant=tenant, amount=Decimal("9000"), payment_date=_dt.date(2026, 9, 5),
        source=PaymentSource.CASH, payment_type=PaymentType.RENT,
        period_month=9, period_year=2026,
    )


@pytest.fixture
def inline_like_production(settings):
    from celery_app import app

    before = app.conf.task_always_eager, app.conf.task_eager_propagates
    app.conf.task_always_eager, app.conf.task_eager_propagates = True, False
    yield
    app.conf.task_always_eager, app.conf.task_eager_propagates = before


def test_a_failed_receipt_inline_is_logged_once_not_raised(payment, inline_like_production, caplog):
    with mock.patch.object(tasks, "_notify_tenant_payment", side_effect=OSError("smtp down")) as notify:
        tasks.send_payment_confirmation.delay(payment.id)  # must not raise
    assert notify.call_count == 1  # no re-runs, so no repeated SMS
    assert "smtp down" in caplog.text


def test_a_failed_deposit_receipt_inline_is_logged_once_not_raised(payment, inline_like_production):
    with mock.patch.object(tasks, "_notify_tenant_payment", side_effect=OSError("smtp down")) as notify:
        tasks.send_deposit_receipt.delay(payment.tenant_id, "9000", "REF1", "2026-09-05")
    assert notify.call_count == 1


def test_with_a_worker_the_task_still_retries_later(payment):
    task = tasks.send_payment_confirmation
    with (
        mock.patch.object(tasks, "_notify_tenant_payment", side_effect=OSError("smtp down")),
        mock.patch.object(task, "retry", side_effect=Retry()) as retry,
    ):
        task.push_request(is_eager=False, retries=0)
        try:
            with pytest.raises(Retry):
                task.run(payment.id)
        finally:
            task.pop_request()
    assert retry.call_args.kwargs["countdown"] == 60
