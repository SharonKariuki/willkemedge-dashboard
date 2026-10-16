"""Project-wide pytest fixtures."""
import pytest


@pytest.fixture(autouse=True)
def _messaging_switches_on(settings):
    """SMS_ENABLED and TENANT_EMAIL_ENABLED default to off in every environment.

    Tests exercise the send paths, so they start with both on; kill-switch tests
    turn them off explicitly.
    """
    settings.SMS_ENABLED = True
    # Never reach the live Africa's Talking account from a test run, even when a
    # developer's .env carries a real key. Tests that need a key set their own.
    settings.AT_API_KEY = ""
    settings.TENANT_EMAIL_ENABLED = True
