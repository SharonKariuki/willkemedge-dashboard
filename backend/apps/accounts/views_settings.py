"""Settings/admin views: login audit log."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LoginAttempt


class LoginAuditView(APIView):
    """GET /api/auth/login-audit/ — recent login attempts."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        attempts = LoginAttempt.objects.all()[:50]
        data = [
            {
                "email": a.email,
                "ip_address": a.ip_address,
                "user_agent": a.user_agent[:80],
                "successful": a.successful,
                "attempted_at": a.attempted_at.isoformat(),
            }
            for a in attempts
        ]
        return Response(data)
