"""Settings/admin views: login audit log."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import access
from .models import LoginAttempt


class LoginAuditView(APIView):
    """GET /api/auth/login-audit/ - recent sign-in attempts.

    Everyone's attempts name other staff, their addresses and their devices,
    so they are for those who may read the activity log (owner, superadmin,
    auditor). Anyone else sees only their own - which is what "my recent
    sign-ins" on Settings is for. Sign-in routes sit outside the central
    access policy (they must work before anyone has a capability), so this
    check lives here.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        attempts = LoginAttempt.objects.all()
        everyone = access.has_capability(request.user, access.Cap.VIEW_ACTIVITY)
        if not everyone:
            attempts = attempts.filter(email__iexact=request.user.email)
        data = [
            {
                "email": a.email,
                "ip_address": a.ip_address,
                "user_agent": a.user_agent[:80],
                "successful": a.successful,
                "cleared_at": a.cleared_at,
                "attempted_at": a.attempted_at.isoformat(),
            }
            for a in attempts[:50]
        ]
        return Response(data, headers={"X-Scope": "everyone" if everyone else "self"})
