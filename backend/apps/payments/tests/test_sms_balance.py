"""
Tests for the Africa's Talking SMS-wallet view (read-only balance + top-up).

  - balance is parsed out of AT's "KES 1785.5000" string and turned into an
    estimated message count
  - an AT outage, a rejected key or an unparseable body degrade to
    balance=null + error, still carrying the top-up paybill
  - a missing AT_API_KEY reads as "not configured", never as a zero balance
  - the result is cached briefly, and ?refresh=1 bypasses the cache
  - auth is required
"""
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.payments import notifications

User = get_user_model()
URL = "/api/notifications/sms-balance/"


@pytest.fixture(autouse=True)
def _clear_balance_cache():
    """The balance is process-cached for 60s — a leak across tests would make
    one test's fake AT response answer the next test's request."""
    cache.delete(notifications._SMS_BALANCE_CACHE_KEY)
    yield
    cache.delete(notifications._SMS_BALANCE_CACHE_KEY)


@pytest.fixture
def auth_client(db):
    user = User.objects.create_user(
        username="osoro", email="o@t.com", password="pw12345678!", role="owner"
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _at_response(payload, status_code=200):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://api.africastalking.com/version1/user"),
    )


@pytest.fixture
def live_at(settings):
    settings.AT_API_KEY = "live-key"
    settings.AT_USERNAME = "wilkem"
    settings.AT_SMS_UNIT_COST = "1.60"
    settings.AT_BALANCE_LOW_THRESHOLD = "500"
    settings.AT_TOPUP_PAYBILL = "525900"
    settings.AT_TOPUP_ACCOUNT = "wilkemedge"
    return settings


def test_returns_parsed_balance_and_estimated_messages(auth_client, live_at):
    with patch("httpx.get", return_value=_at_response({"UserData": {"balance": "KES 1,785.5000"}})):
        res = auth_client.get(URL)

    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert Decimal(body["balance"]) == Decimal("1785.5000")
    assert body["currency"] == "KES"
    # 1785.50 / 1.60 = 1115.9 → floor. An estimate never rounds upward: the
    # failure that matters is telling the director he has messages he doesn't.
    assert body["sms_remaining"] == 1115
    assert body["low"] is False
    assert body["error"] is None


def test_topup_details_come_from_settings_not_the_at_username(auth_client, live_at):
    """The account number is configured, never inferred.

    AT_USERNAME and the top-up account number happen to match on the live
    account, but they are different fields — deriving one from the other would
    quietly point the director's airtime money at the wrong AT wallet the day
    they diverge.
    """
    live_at.AT_USERNAME = "some-other-api-username"
    with patch("httpx.get", return_value=_at_response({"UserData": {"balance": "KES 900.0000"}})):
        body = auth_client.get(URL).json()

    assert body["topup"]["paybill"] == "525900"
    assert body["topup"]["account"] == "wilkemedge"


def test_low_balance_is_flagged(auth_client, live_at):
    with patch("httpx.get", return_value=_at_response({"UserData": {"balance": "KES 120.0000"}})):
        body = auth_client.get(URL).json()

    assert body["low"] is True
    assert body["sms_remaining"] == 75


def test_at_outage_degrades_to_null_balance_but_keeps_the_paybill(auth_client, live_at):
    with patch("httpx.get", side_effect=httpx.ConnectError("no route to host")):
        res = auth_client.get(URL)

    assert res.status_code == 200, "an AT outage must not break the settings page"
    body = res.json()
    assert body["balance"] is None
    assert body["low"] is False
    assert "Africa's Talking" in body["error"]
    assert body["topup"]["paybill"] == "525900"


def test_rejected_api_key_degrades_to_an_error(auth_client, live_at):
    with patch("httpx.get", return_value=_at_response({"detail": "bad key"}, status_code=401)):
        body = auth_client.get(URL).json()

    assert body["balance"] is None
    assert body["error"]


def test_unreadable_balance_is_not_reported_as_zero(auth_client, live_at):
    with patch("httpx.get", return_value=_at_response({"UserData": {"balance": "unavailable"}})):
        body = auth_client.get(URL).json()

    assert body["balance"] is None
    assert body["sms_remaining"] is None
    assert "could not read" in body["error"]


def test_missing_api_key_reads_as_not_configured(auth_client, settings):
    settings.AT_API_KEY = ""
    with patch("httpx.get") as get:
        body = auth_client.get(URL).json()

    assert get.call_count == 0
    assert body["configured"] is False
    assert body["balance"] is None
    assert "not configured" in body["error"]


def test_balance_is_cached_and_refresh_bypasses_the_cache(auth_client, live_at):
    response = _at_response({"UserData": {"balance": "KES 1000.0000"}})
    with patch("httpx.get", return_value=response) as get:
        first = auth_client.get(URL).json()
        second = auth_client.get(URL).json()
        assert get.call_count == 1, "a second page load must not re-hit AT"
        assert second["cached"] is True
        assert first["balance"] == second["balance"]

        auth_client.get(URL, {"refresh": "1"})
        assert get.call_count == 2


def test_failed_lookup_is_not_cached(auth_client, live_at):
    """A transient outage must not pin an error on the card for a full minute."""
    with patch("httpx.get", side_effect=httpx.ConnectError("down")):
        assert auth_client.get(URL).json()["balance"] is None
    with patch("httpx.get", return_value=_at_response({"UserData": {"balance": "KES 50.0000"}})):
        body = auth_client.get(URL).json()

    assert Decimal(body["balance"]) == Decimal("50.0000")


def test_requires_authentication(db):
    assert APIClient().get(URL).status_code == 401
