"""Auth views: health, login, logout, current user, password reset."""
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from .serializers import (
    LoginSerializer,
    LogoutSerializer,
    UserSerializer,
)
from .services import is_locked_out, record_login_attempt


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class LoginView(APIView):
    """POST /api/auth/login/"""
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
    """POST /api/auth/logout/ — blacklist the refresh token."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(APIView):
    """GET /api/auth/me/ — return current authenticated user."""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(UserSerializer(request.user).data)


RefreshView = TokenRefreshView


# ---------------------------------------------------------------------------
# Password Reset — Task 5.10
# ---------------------------------------------------------------------------

class PasswordResetRequestView(APIView):
    """
    POST /api/auth/password-reset/
    Body: {"email": "william@gmail.com"}

    Generates a PasswordResetToken, emails the link via SendGrid.
    Always returns 200 regardless of whether the email exists
    (prevents user enumeration).
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        from .models import PasswordResetToken, User
        from .tasks import send_password_reset_email

        email = (request.data.get("email") or "").lower().strip()
        try:
            user = User.objects.get(email=email, is_active=True)
            token_obj = PasswordResetToken.create_for_user(user)
            send_password_reset_email.delay(user.id, token_obj.token)
        except User.DoesNotExist:
            pass  # Silent — don't reveal whether email exists

        return Response(
            {"detail": "If that email is registered you will receive a reset link."}
        )


class PasswordResetConfirmView(APIView):
    """
    POST /api/auth/password-reset/confirm/
    Body: {"token": "...", "new_password": "..."}

    Validates the token, sets the new password, marks token as used,
    and blacklists all existing refresh tokens for that user.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        from .models import PasswordResetToken

        token_str = (request.data.get("token") or "").strip()
        new_password = request.data.get("new_password", "")

        if not token_str or not new_password:
            return Response(
                {"detail": "token and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token_obj = PasswordResetToken.objects.select_related("user").get(
                token=token_str
            )
        except PasswordResetToken.DoesNotExist:
            return Response(
                {"detail": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not token_obj.is_valid:
            return Response(
                {"detail": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = token_obj.user

        # Validate password strength via Django's validators.
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        try:
            validate_password(new_password, user=user)
        except ValidationError as exc:
            return Response({"detail": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        # Commit changes.
        user.set_password(new_password)
        user.save(update_fields=["password"])
        token_obj.used = True
        token_obj.save(update_fields=["used"])

        # Blacklist all outstanding JWT refresh tokens for this user.
        for outstanding in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=outstanding)

        return Response({"detail": "Password updated successfully."})

