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

        # Content-Security-Policy — report-only in dev for convenience.
        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self' http://localhost:8000; "
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
