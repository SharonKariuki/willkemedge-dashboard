"""Where an audited action came from — held for the length of one request or command.

The audit log answers "who did this, from where, and in which sitting". Most of
that is not known at the point a row is written: a service saving a Unit has no
request object, and a management command has no user at all. So the entry
points (the HTTP middleware, `manage.py`) open a context here, and
`audit.record()` reads it.

Deliberately free of Django imports so `manage.py` can open a command context
before settings are configured.
"""
from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field


class Source:
    """What set the action off. Stored on every audit row."""

    WEB = "web"          # a signed-in person using the dashboard
    ADMIN = "admin"      # the Django admin
    BANK = "bank"        # a Co-op Bank / M-Pesa notification
    CRON = "cron"        # the scheduled-job endpoints
    COMMAND = "command"  # `python manage.py <command>`, usually on the Render shell
    SYSTEM = "system"    # anything else (tests, background tasks)

    CHOICES = [
        (WEB, "Dashboard"),
        (ADMIN, "Admin site"),
        (BANK, "Bank notification"),
        (CRON, "Scheduled job"),
        (COMMAND, "Server command"),
        (SYSTEM, "System"),
    ]


@dataclass
class AuditContext:
    source: str = Source.SYSTEM
    #: Command name, cron job slug, or request path — whatever narrows `source`.
    source_detail: str = ""
    #: The Django HttpRequest, when there is one. The actor is read from it
    #: lazily because DRF authenticates inside the view, after middleware runs.
    request: object | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    #: A command announces itself once, on its first audited write.
    announced: bool = False
    #: Full argv of a command, for its announcement row.
    argv: list[str] = field(default_factory=list)


_current: contextvars.ContextVar[AuditContext | None] = contextvars.ContextVar(
    "audit_context", default=None
)


def current() -> AuditContext:
    """The open context, or a throwaway SYSTEM one when nothing opened a context."""
    return _current.get() or AuditContext()


@contextmanager
def bind(ctx: AuditContext):
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def start_command(argv: list[str]) -> None:
    """Mark the rest of this process as one server command. Called from manage.py.

    Not scoped with `bind`: the command owns the process until it exits.
    """
    name = argv[1] if len(argv) > 1 else ""
    _current.set(AuditContext(source=Source.COMMAND, source_detail=name, argv=list(argv[1:])))
