"""
Security headers middleware.
Adds CSP, Permissions-Policy, and other hardening headers.
"""
from django.conf import settings


class SecurityHeadersMiddleware:
    """Append security-related HTTP headers to every response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # connect-src is parameterized from settings so production never ships
        # a hardcoded localhost origin. Defaults to 'self' plus whatever
        # CSP_CONNECT_SRC provides (empty in prod unless configured).
        extra_connect = " ".join(getattr(settings, "CSP_CONNECT_SRC", []) or [])
        connect_src = ("'self' " + extra_connect).strip()

        # Content-Security-Policy — report-only in dev for convenience.
        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            f"connect-src {connect_src}; "
            "frame-ancestors 'none'"
        )
        if settings.DEBUG:
            response["Content-Security-Policy-Report-Only"] = csp
        else:
            response["Content-Security-Policy"] = csp

        response["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        )
        response["X-Content-Type-Options"] = "nosniff"

        return response


class AuditContextMiddleware:
    """Opens the audit context for each request: where it came from, and who.

    Also records a DENIED row when a signed-in person is refused a change —
    a caretaker trying to void a payment is worth the director knowing about.
    Must sit after AuthenticationMiddleware so admin requests carry their user.
    """

    #: Path prefix → (source, detail). First match wins; anything else is WEB.
    ROUTES = (
        ("/admin/", "admin", ""),
        ("/api/payments/coop/ipn/", "bank", "coop-ipn"),
        ("/api/payments/coop/reconcile-daily/", "cron", "daily-reconciliation"),
        ("/api/payments/cron/", "cron", None),  # detail = the job slug
    )

    def __init__(self, get_response):
        self.get_response = get_response

    @classmethod
    def source_for(cls, path: str) -> tuple[str, str]:
        for prefix, source, detail in cls.ROUTES:
            if path.startswith(prefix):
                if detail is None:
                    detail = path[len(prefix):].strip("/")
                return source, detail or path
        return "web", path

    def __call__(self, request):
        from .audit_context import AuditContext, bind

        source, detail = self.source_for(request.path)
        with bind(AuditContext(source=source, source_detail=detail[:120], request=request)):
            response = self.get_response(request)
            if response.status_code == 403 and request.method not in ("GET", "HEAD", "OPTIONS"):
                self._record_denied(request)
        return response

    @staticmethod
    def _record_denied(request) -> None:
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return
        from . import audit

        audit.record(
            kind="denied",
            action="access.denied",
            object_type="request",
            object_id=None,
            object_label=request.path[:150],
            summary=(
                f"Refused: {request.method} {request.path} "
                f"(role: {getattr(user, 'get_role_display', lambda: '')() or 'unknown'})"
            ),
            is_financial=False,
        )
