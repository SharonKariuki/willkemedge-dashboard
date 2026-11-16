"""Every API route against every role - walked from the URL list, not hand-kept.

A route added later is covered without anyone remembering to add it here, so
this is what notices an endpoint that lets a read-only role write, or shows a
caretaker the books. Requests carry real JWTs: the access policy lives in the
authentication class, which DRF's ``force_authenticate`` would skip.

The expectations below are written independently of ``access.RULES`` on
purpose: they say what each role should reach in plain terms, so a change to
the rules that widens access fails here instead of passing quietly.
"""
import datetime as dt
import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role

User = get_user_model()

#: Routes that answer before anyone signs in, or carry their own secret.
PUBLIC = re.compile(
    r"^/api/(health/|auth/(login|refresh|logout|password-reset|invite)|payments/(coop|cron)/)"
)
#: Routes about the signed-in person themselves.
OWN_ACCOUNT = re.compile(r"^/api/auth/(me|change-password|login-audit)/")
#: Downloading a report is reading it, though the browser POSTs the table.
READ_BY_POST = re.compile(r"^/api/reports/export/")
#: What a caretaker reads: their buildings' property records, maintenance and water.
CARETAKER_READS = re.compile(
    r"^/api/(buildings|units|maintenance)/"
    r"|^/api/tenants/(?!export/|email-statements?/)(?![^/]+/(payment-history|statement-pdf|email-statements?)/)"
    r"|^/api/utility-charges/($|previous-reading/|reading/)"
)


def _concrete(route: str) -> str | None:
    """A request path for a URL pattern, or None for one we can't fill in."""
    if "format" in route:
        return None  # DRF's ".json" suffix twins of routes already covered
    route = route.replace("^", "").replace("$", "")
    route = re.sub(r"\(\?P<[^>]+>[^)]*\)", "1", route)
    route = re.sub(r"<int:[^>]+>", "1", route)
    route = re.sub(r"<(str|slug):[^>]+>", "x", route)
    route = route.replace("\\.", ".")
    if re.search(r"[\[\]()*+?|\\{}]", route):
        return None
    return "/" + route


def _walk(patterns, prefix=""):
    for p in patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, route)
        elif isinstance(p, URLPattern):
            yield route


def api_paths() -> list[str]:
    paths = {_concrete(r) for r in _walk(get_resolver().url_patterns)}
    return sorted(p for p in paths if p and p.startswith("/api/"))


PATHS = api_paths()
GUARDED = [p for p in PATHS if not PUBLIC.match(p)]


def _person(role, **extra):
    email = f"{role}@matrix.example.com"
    user = User.objects.create_user(username=email, email=email, password="Rent-roll-2026!", role=role)
    for k, v in extra.items():
        setattr(user, k, v)
    user.save()
    return user


def _client(user=None):
    c = APIClient()
    if user is not None:
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return c


def test_the_walk_finds_the_api():
    # Guards the walker itself: if it silently found nothing, every test below
    # would pass by checking nothing.
    assert len(GUARDED) > 60
    for expected in ("/api/payments/1/void/", "/api/arrears/1/waive/", "/api/expenses/",
                     "/api/deposit-settlements/", "/api/auth/users/", "/api/tenants/export/"):
        assert expected in PATHS, expected


@pytest.mark.django_db
@pytest.mark.parametrize("path", GUARDED)
def test_nobody_signed_out_gets_in(path):
    for method in ("get", "post"):
        status = getattr(_client(), method)(path, {}, format="json").status_code
        assert status in (401, 403), f"{method.upper()} {path} answered {status} to nobody"


@pytest.mark.django_db
@pytest.mark.parametrize("role", [Role.VIEWER, Role.AUDITOR])
def test_read_only_roles_change_nothing(role):
    extra = {"access_expires_on": timezone.localdate() + dt.timedelta(days=30)} if role == Role.AUDITOR else {}
    c = _client(_person(role, **extra))
    let_through = []
    for path in GUARDED:
        if OWN_ACCOUNT.match(path) or READ_BY_POST.match(path):
            continue
        for method in ("post", "patch", "delete"):
            status = getattr(c, method)(path, {}, format="json").status_code
            # 405: a read-only route turning the method away - nothing changed either way.
            if status not in (403, 405):
                let_through.append(f"{method.upper()} {path} -> {status}")
    assert not let_through, "\n".join(let_through)


@pytest.mark.django_db
def test_a_caretaker_reads_only_property_maintenance_and_water():
    from apps.buildings.models import Building

    caretaker = _person(Role.CARETAKER)
    caretaker.buildings.set([Building.objects.create(name="Block A", address="Nairobi")])
    c = _client(caretaker)
    wrong = []
    for path in GUARDED:
        if OWN_ACCOUNT.match(path):
            continue
        status = c.get(path).status_code
        should_reach = bool(CARETAKER_READS.match(path))
        if should_reach and status == 403:
            wrong.append(f"refused {path}")
        if not should_reach and status != 403:
            wrong.append(f"reached {path} -> {status}")
    assert not wrong, "\n".join(wrong)


@pytest.mark.django_db
def test_only_those_who_manage_users_reach_the_users_page():
    for role in (Role.ACCOUNTANT, Role.VIEWER, Role.CARETAKER):
        assert _client(_person(role)).get("/api/auth/users/").status_code == 403
