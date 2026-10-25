"""Auth views: health, login, logout, current user, password reset."""
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from . import audit
from .permissions import IsOwner
from .serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    LogoutSerializer,
    PasswordResetConfirmSerializer,
    UserSerializer,
)
from .services import (
    clear_failed_attempts,
    forwarded_chain,
    get_client_ip,
    is_locked_out,
    record_login_attempt,
)


def _record_auth(action: str, summary: str, email: str, *, actor=None, session_id=None) -> None:
    audit.record(
        kind="auth",
        action=action,
        object_type="user",
        object_id=getattr(actor, "pk", None),
        object_label=email,
        summary=summary,
        actor=actor,
        is_financial=False,
        session_id=session_id,
    )


class ClientIpDebugView(APIView):
    """GET /api/auth/client-ip/ — owner only. What the proxies in front of the
    app sent for this request, so CLIENT_IP_HEADER / TRUSTED_PROXY_HOPS can be
    set from facts rather than guesses. Shows only the caller's own address."""

    permission_classes = [IsOwner]

    def get(self, request):
        meta = request.META
        return Response({
            "resolved_ip": get_client_ip(request),
            "x_forwarded_for": forwarded_chain(request),
            "remote_addr": meta.get("REMOTE_ADDR"),
            "cf_connecting_ip": meta.get("HTTP_CF_CONNECTING_IP"),
            "true_client_ip": meta.get("HTTP_TRUE_CLIENT_IP"),
            "x_real_ip": meta.get("HTTP_X_REAL_IP"),
            "configured": {
                "CLIENT_IP_HEADER": settings.CLIENT_IP_HEADER,
                "TRUSTED_PROXY_HOPS": settings.TRUSTED_PROXY_HOPS,
            },
        })


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class LoginView(APIView):
    """POST /api/auth/login/"""
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        email = (request.data.get("email") or "").lower().strip()
        ip_address = get_client_ip(request)

        if email and is_locked_out(email, ip_address):
            record_login_attempt(email=email, request=request, successful=False)
            _record_auth("auth.locked_out", f"Sign-in blocked for {email}: too many failed attempts", email)
            return Response(
                {"detail": "Account temporarily locked. Try again in 30 minutes."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            if email:
                record_login_attempt(email=email, request=request, successful=False)
                _record_auth("auth.login_failed", f"Failed sign-in for {email}", email)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        record_login_attempt(email=email, request=request, successful=True)
        # Successful auth resets the rolling failed-attempt window so a user
        # who fumbled their password isn't left near the lockout threshold.
        clear_failed_attempts(email)
        _record_auth(
            "auth.login", "Signed in", email,
            actor=serializer.user, session_id=serializer.session_id,
        )
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """POST /api/auth/logout/ — blacklist the refresh token."""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        _record_auth("auth.logout", "Signed out", request.user.email, actor=request.user)
        return Response(status=status.HTTP_205_RESET_CONTENT)


def _blacklist_all_refresh_tokens(user) -> None:
    """Invalidate every outstanding refresh token for a user.

    Called after a password change so a session opened with the OLD password —
    an attacker's, if that is why the password is being changed — cannot be
    refreshed back to life. The caller is issued a fresh pair so the person who
    made the change stays signed in.
    """
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)


class ChangePasswordView(APIView):
    """POST /api/auth/change-password/ — change your own password.

    Body: {"current_password": "...", "new_password": "..."}

    This is the routine way to change a password, and the only one with no
    email in the loop: nothing is mailed, so there is no link to intercept.
    The route was missing entirely, so the Settings page posted here and got
    a 404 — the reason no one could change a password from the application.

    The change invalidates every outstanding refresh token and returns a fresh
    pair, so other sessions are signed out while the caller is not.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from rest_framework_simplejwt.tokens import RefreshToken

        serializer = ChangePasswordSerializer(
            data=request.data, context={"user": request.user}
        )
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        _blacklist_all_refresh_tokens(user)
        refresh = RefreshToken.for_user(user)

        return Response({
            "detail": "Password updated. Other sessions have been signed out.",
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        })


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

    Generates a PasswordResetToken, emails the link via Gmail SMTP.
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
            _record_auth("auth.password_reset_request", f"Password reset link requested for {email}", email)
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
        from .models import PasswordResetToken

        # Validate shape + password strength via the serializer.
        serializer = PasswordResetConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        token_str = serializer.validated_data["token"].strip()
        new_password = serializer.validated_data["new_password"]

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
        _blacklist_all_refresh_tokens(user)

        _record_auth("auth.password_reset", "Reset password from an emailed link", user.email, actor=user)
        return Response({"detail": "Password updated successfully."})

