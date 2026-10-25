"""A repeated bulk send must not message the same tenants twice.

The compose-and-send runs in one request. When the browser gave up first, the
office saw "failed" while the server kept sending, clicked again, and every
tenant got the message twice. Tenants who got the same text in the last few
minutes are now skipped and reported.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import NotificationStatus, TenantNotification
from apps.payments.notification_services import resolve_placeholders
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()


@pytest.fixture
def client(db):
    c = APIClient()
    c.force_authenticate(User.objects.create_user(username="o", email="o@x.com", password="x", role="owner"))
    return c


def _tenant(label, first):
    building, _ = Building.objects.get_or_create(name="Road Block", defaults={"total_floors": 2})
    unit = Unit.objects.create(
        building=building, label=label, monthly_rent=Decimal("10000"), status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name=first, last_name="T", id_number=label, phone="+254700000001", unit=unit,
        monthly_rent=Decimal("10000"), move_in_date="2026-01-01", status=TenantStatus.ACTIVE,
    )


def _deliver(notification, automatic=False):
    """Stand-in for dispatch: personalise the text, mark it sent."""
    notification.body = resolve_placeholders(notification.body, notification.tenant)
    notification.status = NotificationStatus.SENT
    notification.save()
    return notification


def _send(client, tenants, body):
    return client.post(
        "/api/notifications/send/",
        {"audience": "tenant", "tenant_ids": [t.id for t in tenants], "channel": "sms", "body": body},
        format="json",
    )


@patch("apps.payments.notification_views.dispatch_notification", side_effect=_deliver)
def test_a_repeat_skips_tenants_who_just_got_it(mock_dispatch, client):
    a, b = _tenant("A1", "Amina"), _tenant("A2", "Baraka")
    body = "Hello {tenant_name}, water is off tomorrow."  # personalised per tenant

    first = _send(client, [a], body)
    assert first.data["sent"] == 1

    again = _send(client, [a, b], body)
    assert again.status_code == 201
    assert again.data["sent"] == 1  # only Baraka
    assert again.data["skipped"] == 1
    assert [s["tenant"] for s in again.data["skipped_tenants"]] == [a.id]
    assert TenantNotification.objects.filter(tenant=a).count() == 1


@patch("apps.payments.notification_views.dispatch_notification", side_effect=_deliver)
def test_a_different_message_still_goes(mock_dispatch, client):
    a = _tenant("B1", "Amina")
    _send(client, [a], "Water is off tomorrow.")
    res = _send(client, [a], "Water is back on.")
    assert res.data["sent"] == 1 and res.data["skipped"] == 0
