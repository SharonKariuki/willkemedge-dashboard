"""
Tests for emailing tenants their rent statement as a PDF.

Covers:
  - a statement is emailed with the PDF attached, and recorded as a notification
  - the monthly run is idempotent per tenant per month, but retries failures
  - tenants with no email are counted, not written to the notification history
  - an unconfigured mailbox is recorded as FAILED, never as a silent success
  - the master switch silences the scheduled run but not a manual send
  - the single and bulk API endpoints report per-tenant outcomes
  - a batch sends over one SMTP connection rather than one per tenant
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.buildings.models import Building, Unit, UnitStatus
from apps.payments.models import (
    NotificationChannel,
    NotificationStatus,
    TenantNotification,
)
from apps.payments.statement_delivery import open_mail_connection, send_tenant_statement
from apps.payments.tasks import send_monthly_statements
from apps.tenants.models import Tenant, TenantStatus

User = get_user_model()
AS_AT = date(2026, 9, 2)


@pytest.fixture(autouse=True)
def _smtp_configured(settings):
    """send_email refuses to send with no credentials, which every test here
    would otherwise hit as a FAILED row rather than exercising the real path."""
    settings.EMAIL_HOST_USER = "wilkem.ventures@gmail.com"
    settings.EMAIL_HOST_PASSWORD = "app-password"
    settings.TENANT_NOTIFICATIONS_ENABLED = True


@pytest.fixture
def building(db):
    return Building.objects.create(name="Road Block", total_floors=4)


def _make_tenant(building, *, email="tenant@example.com", id_number="T1",
                 status=TenantStatus.ACTIVE):
    unit = Unit.objects.create(
        building=building, label=f"RB-{id_number}", monthly_rent=Decimal("20000"),
        status=UnitStatus.OCCUPIED_UNPAID,
    )
    return Tenant.objects.create(
        first_name="Sarah", last_name="Hamisi", id_number=id_number,
        phone="+254726012481", email=email, unit=unit,
        monthly_rent=Decimal("20000"), move_in_date="2026-01-01", status=status,
    )


class TestSendTenantStatement:
    def test_emails_the_statement_with_the_pdf_attached(self, building):
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            note = send_tenant_statement(tenant, statement_date=AS_AT)

        assert note.status == NotificationStatus.SENT
        assert note.channel == NotificationChannel.EMAIL
        assert note.template_key == "rent_statement"
        assert note.sent_at is not None

        to_email, subject, html = send.call_args.args
        assert to_email == "tenant@example.com"
        assert "Road Block" in subject and "RB-T1" in subject
        attachments = send.call_args.kwargs["attachments"]
        assert len(attachments) == 1
        filename, content, mimetype = attachments[0]
        assert filename == "Rent_Statement_Sarah_Hamisi.pdf"
        assert mimetype == "application/pdf"
        assert content[:4] == b"%PDF"
        # The body carries the statement too, so the email stands on its own.
        assert "CUSTOMER RENT STATEMENT AS AT" in html

    def test_body_asks_for_settlement_rather_than_thanking_for_a_payment(self, building):
        """The receipt flavour thanks the tenant for money they sent; a statement
        run has no payment behind it and must not claim one."""
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            send_tenant_statement(tenant, statement_date=AS_AT)

        html = send.call_args.args[2]
        assert "Thank you for your payment" not in html
        assert "payable on or before" in html

    def test_records_a_short_summary_not_the_whole_html(self, building):
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_email", return_value=True):
            note = send_tenant_statement(tenant, statement_date=AS_AT)

        assert "<html>" not in note.body
        assert "Road Block RB-T1" in note.body
        assert len(note.body) < 300

    def test_tenant_with_no_email_fails_with_the_reason(self, building):
        tenant = _make_tenant(building, email="")
        with patch("apps.payments.notifications.send_email") as send:
            note = send_tenant_statement(tenant, statement_date=AS_AT)

        send.assert_not_called()
        assert note.status == NotificationStatus.FAILED
        assert "no email address" in note.error

    def test_unconfigured_mailbox_is_a_failure_not_a_silent_success(self, building, settings):
        """send_email skips when no credentials are set. Recording that as SENT
        would report a whole run as delivered to a mailbox nobody opened."""
        settings.EMAIL_HOST_USER = ""
        settings.EMAIL_HOST_PASSWORD = ""
        tenant = _make_tenant(building)

        note = send_tenant_statement(tenant, statement_date=AS_AT)

        assert note.status == NotificationStatus.FAILED
        assert "not configured" in note.error

    def test_smtp_error_is_recorded_and_does_not_raise(self, building):
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_email",
                   side_effect=OSError("relay refused")):
            note = send_tenant_statement(tenant, statement_date=AS_AT)

        assert note.status == NotificationStatus.FAILED
        assert "relay refused" in note.error

    def test_master_switch_suppresses_the_scheduled_send_only(self, building, settings):
        settings.TENANT_NOTIFICATIONS_ENABLED = False
        tenant = _make_tenant(building)

        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            automatic = send_tenant_statement(tenant, statement_date=AS_AT)
            assert automatic.status == NotificationStatus.PENDING
            send.assert_not_called()

            manual = send_tenant_statement(tenant, statement_date=AS_AT, automatic=False)
            assert manual.status == NotificationStatus.SENT
            send.assert_called_once()


class TestMonthlyStatementRun:
    def test_sends_to_active_tenants_with_an_email(self, building):
        _make_tenant(building, id_number="T1")
        _make_tenant(building, id_number="T2", email="second@example.com")

        with patch("apps.payments.notifications.send_email", return_value=True):
            counts = send_monthly_statements(AS_AT.isoformat())

        assert counts["sent"] == 2
        assert counts["as_at"] == "2026-09-02"
        assert TenantNotification.objects.filter(status=NotificationStatus.SENT).count() == 2

    def test_tenants_without_an_email_are_counted_not_recorded(self, building):
        """Most of the roster has no address on file. A failure row each for all
        of them, every month, would bury the failures that can be acted on."""
        _make_tenant(building, id_number="T1", email="")
        _make_tenant(building, id_number="T2", email="")

        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            counts = send_monthly_statements(AS_AT.isoformat())

        send.assert_not_called()
        assert counts == {"sent": 0, "failed": 0, "skipped": 0, "no_email": 2,
                          "as_at": "2026-09-02", "period": "2026-09"}
        assert TenantNotification.objects.count() == 0

    def test_skips_tenants_who_are_not_active(self, building):
        _make_tenant(building, id_number="T1", status=TenantStatus.MOVED_OUT)

        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            counts = send_monthly_statements(AS_AT.isoformat())

        send.assert_not_called()
        assert counts["sent"] == 0

    def test_rerunning_the_same_month_does_not_send_twice(self, building):
        _make_tenant(building)

        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            first = send_monthly_statements(AS_AT.isoformat())
            second = send_monthly_statements(AS_AT.isoformat())

        assert first["sent"] == 1
        assert second == {"sent": 0, "failed": 0, "skipped": 1, "no_email": 0,
                          "as_at": "2026-09-02", "period": "2026-09"}
        assert send.call_count == 1

    def test_a_failed_send_is_retried_on_the_next_run(self, building):
        """The point of keeping failures on record: a transient SMTP refusal is
        picked up by a re-run, where a blanket dedupe would strand it."""
        _make_tenant(building)

        with patch("apps.payments.notifications.send_email",
                   side_effect=OSError("timeout")):
            first = send_monthly_statements(AS_AT.isoformat())
        with patch("apps.payments.notifications.send_email", return_value=True):
            second = send_monthly_statements(AS_AT.isoformat())

        assert first["failed"] == 1
        assert second["sent"] == 1

    def test_a_month_only_argument_dates_the_statement_to_the_month_end(self, building):
        """Re-issuing a month that has closed dates the statement to its last
        day, whatever today happens to be."""
        _make_tenant(building)

        with patch("apps.payments.notifications.send_email", return_value=True), \
             patch("apps.payments.tasks.timezone.localdate",
                   return_value=date(2026, 11, 4)):
            counts = send_monthly_statements("2026-08")

        assert counts["as_at"] == "2026-08-31"
        assert counts["period"] == "2026-08"

    def test_a_month_that_has_not_closed_is_dated_today_not_in_the_future(self, building):
        """The advance run states September from 25 August. Re-issuing it that
        week must not print a statement drawn on 30 September."""
        _make_tenant(building)

        with patch("apps.payments.notifications.send_email", return_value=True), \
             patch("apps.payments.tasks.timezone.localdate",
                   return_value=date(2026, 8, 26)):
            counts = send_monthly_statements("2026-09")

        assert counts["as_at"] == "2026-08-26"
        assert counts["period"] == "2026-09"

    def test_a_bad_period_falls_back_to_today_rather_than_crashing(self, building):
        _make_tenant(building)

        with patch("apps.payments.notifications.send_email", return_value=True):
            counts = send_monthly_statements("not-a-date")

        assert counts["sent"] == 1


class TestStatementEmailApi:
    @pytest.fixture
    def auth_client(self, db):
        user = User.objects.create_user(
            username="admin", email="a@t.com", password="pw12345678!", role="owner"
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_single_send(self, auth_client, building):
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            res = auth_client.post(f"/api/tenants/{tenant.id}/email-statement/")

        assert res.status_code == 201
        assert res.data["sent"] == 1
        assert res.data["notifications"][0]["tenant"] == tenant.id
        send.assert_called_once()

    def test_single_send_reports_a_missing_email_address(self, auth_client, building):
        tenant = _make_tenant(building, email="")
        res = auth_client.post(f"/api/tenants/{tenant.id}/email-statement/")

        assert res.status_code == 201
        assert res.data["sent"] == 0 and res.data["failed"] == 1
        assert "no email address" in res.data["notifications"][0]["error"]

    def test_bulk_send_reports_every_tenant_asked_for(self, auth_client, building):
        ok = _make_tenant(building, id_number="T1")
        no_email = _make_tenant(building, id_number="T2", email="")

        with patch("apps.payments.notifications.send_email", return_value=True):
            res = auth_client.post(
                "/api/tenants/email-statements/",
                {"tenant_ids": [ok.id, no_email.id]},
                format="json",
            )

        assert res.status_code == 201
        assert res.data["sent"] == 1
        assert res.data["failed"] == 1
        assert res.data["total"] == 2

    def test_bulk_send_is_not_deduped(self, auth_client, building):
        """The office re-sends on request; a manual send must never be swallowed
        as a duplicate of the monthly run."""
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            auth_client.post("/api/tenants/email-statements/",
                             {"tenant_ids": [tenant.id]}, format="json")
            auth_client.post("/api/tenants/email-statements/",
                             {"tenant_ids": [tenant.id]}, format="json")

        assert send.call_count == 2

    def test_bulk_send_rejects_an_empty_selection(self, auth_client):
        res = auth_client.post("/api/tenants/email-statements/",
                               {"tenant_ids": []}, format="json")
        assert res.status_code == 400

    def test_endpoints_require_authentication(self, db, building):
        tenant = _make_tenant(building)
        client = APIClient()
        assert client.post(
            f"/api/tenants/{tenant.id}/email-statement/"
        ).status_code in (401, 403)
        assert client.post(
            "/api/tenants/email-statements/",
            {"tenant_ids": [tenant.id]}, format="json",
        ).status_code in (401, 403)


class TestBatchedMailConnection:
    """The SMTP handshake, not the PDF, is what makes a batch slow, so a run
    opens one connection and every statement in it goes over that."""

    def test_a_batch_reuses_one_connection(self, building):
        _make_tenant(building, id_number="T1")
        _make_tenant(building, id_number="T2", email="second@example.com")

        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            send_monthly_statements(AS_AT.isoformat())

        connections = [c.kwargs["connection"] for c in send.call_args_list]
        assert len(connections) == 2
        assert connections[0] is not None
        assert connections[0] is connections[1]

    def test_the_bulk_endpoint_reuses_one_connection(self, db, building):
        user = User.objects.create_user(
            username="admin2", email="a2@t.com", password="pw12345678!", role="owner"
        )
        client = APIClient()
        client.force_authenticate(user=user)
        first = _make_tenant(building, id_number="T1")
        second = _make_tenant(building, id_number="T2", email="second@example.com")

        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            client.post("/api/tenants/email-statements/",
                        {"tenant_ids": [first.id, second.id]}, format="json")

        connections = [c.kwargs["connection"] for c in send.call_args_list]
        assert len(connections) == 2
        assert connections[0] is not None and connections[0] is connections[1]

    def test_a_single_send_still_opens_its_own_connection(self, building):
        """A one-off send has nothing to amortise, so it keeps the default
        per-message connection rather than managing one for a batch of one."""
        tenant = _make_tenant(building)
        with patch("apps.payments.notifications.send_email", return_value=True) as send:
            send_tenant_statement(tenant, statement_date=AS_AT)

        assert send.call_args.kwargs["connection"] is None

    def test_no_credentials_yields_no_connection(self, settings):
        """send_email refuses to send at all without credentials, so opening a
        connection first would only raise somewhere less informative."""
        settings.EMAIL_HOST_USER = ""
        settings.EMAIL_HOST_PASSWORD = ""
        with open_mail_connection() as connection:
            assert connection is None

    def test_a_connection_that_will_not_open_falls_back_rather_than_failing(self):
        """One refused handshake must not take the whole run with it — each
        statement can still try on its own."""
        with patch("django.core.mail.get_connection") as get_conn:
            get_conn.return_value.open.side_effect = OSError("connection refused")
            with open_mail_connection() as connection:
                assert connection is None
