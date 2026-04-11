"""Auth views: health, login, logout, current user."""
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from .serializers import LoginSerializer, LogoutSerializer, UserSerializer
from .services import is_locked_out, record_login_attempt


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class LoginView(APIView):
    """
    POST /api/auth/login/
    Body: {"email": "...", "password": "..."}

    Returns access + refresh tokens. Records every attempt to LoginAttempt
    and refuses any login for an email currently locked out.
    """

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        email = (request.data.get("email") or "").lower().strip()

        if email and is_locked_out(email):
            record_login_attempt(email=email, request=request, successful=False)
            return Response(
                {"detail": "Account temporarily locked. Try again in 30 minutes."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            if email:
                record_login_attempt(email=email, request=request, successful=False)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        record_login_attempt(email=email, request=request, successful=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """POST /api/auth/logout/  — blacklist the refresh token."""

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(APIView):
    """GET /api/auth/me/  — return current authenticated user."""

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(UserSerializer(request.user).data)


# Re-export simplejwt's refresh view so urls.py only imports from one place.
RefreshView = TokenRefreshView
