"""Tests for the change_login_email management command."""
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

User = get_user_model()

PASSWORD = "SecurePass123!"
OLD = "william@gmail.com"
NEW = "wilkem.ventures@gmail.com"


@pytest.fixture
def owner(db):
    return User.objects.create_superuser(
        username="owner", email=OLD, password=PASSWORD, role="owner"
    )


def run(*args):
    out = StringIO()
    call_command("change_login_email", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestChangeLoginEmail:
    def test_dry_run_writes_nothing(self, owner):
        out = run("--to", NEW)
        assert NEW in out
        owner.refresh_from_db()
        assert owner.email == OLD

    def test_apply_changes_the_email(self, owner):
        run("--to", NEW, "--apply")
        owner.refresh_from_db()
        assert owner.email == NEW

    def test_password_survives_the_change(self, owner):
        run("--to", NEW, "--apply")
        owner.refresh_from_db()
        assert owner.check_password(PASSWORD)

    def test_new_email_logs_in(self, owner, client):
        run("--to", NEW, "--apply")
        res = client.post(
            "/api/auth/login/",
            {"email": NEW, "password": PASSWORD},
            content_type="application/json",
        )
        assert res.status_code == 200

    def test_rerun_is_a_no_op(self, owner):
        run("--to", NEW, "--apply")
        out = run("--to", NEW, "--apply")
        assert "already" in out.lower()

    def test_target_is_uppercased_and_trimmed(self, owner):
        run("--to", "  WILKEM.Ventures@Gmail.com ", "--apply")
        owner.refresh_from_db()
        assert owner.email == NEW

    def test_explicit_from_picks_the_account(self, owner):
        other = User.objects.create_user(
            username="clerk", email="clerk@test.com", password=PASSWORD
        )
        run("--from", "clerk@test.com", "--to", NEW, "--apply")
        other.refresh_from_db()
        owner.refresh_from_db()
        assert other.email == NEW
        assert owner.email == OLD

    def test_unknown_from_is_an_error(self, owner):
        with pytest.raises(CommandError, match="No account"):
            run("--from", "nobody@test.com", "--to", NEW, "--apply")

    def test_collision_names_the_other_account(self, owner):
        User.objects.create_user(username="clerk", email=NEW, password=PASSWORD)
        with pytest.raises(CommandError, match="already belongs"):
            run("--to", NEW, "--apply")
        owner.refresh_from_db()
        assert owner.email == OLD

    def test_invalid_email_is_rejected(self, owner):
        with pytest.raises(CommandError, match="not a valid email"):
            run("--to", "not-an-email", "--apply")

    def test_two_superusers_refuse_to_guess(self, owner):
        User.objects.create_superuser(
            username="second", email="second@test.com", password=PASSWORD
        )
        with pytest.raises(CommandError, match="More than one superuser"):
            run("--to", NEW, "--apply")
