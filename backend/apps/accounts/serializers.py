"""Auth serializers."""
import uuid

from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    """Email + password login. Returns access + refresh tokens."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        email = attrs["email"].lower().strip()
        password = attrs["password"]

        user = authenticate(
            request=self.context.get("request"),
            username=email,
            password=password,
        )
        if user is None:
            raise serializers.ValidationError(
                {"detail": "Invalid email or password."}
            )
        if not user.is_active:
            raise serializers.ValidationError(
                {"detail": "Account is disabled."}
            )

        refresh = RefreshToken.for_user(user)
        # One id per sign-in. simplejwt copies custom claims onto every access
        # token and keeps them through refresh rotation, so every request made
        # in this sitting carries it and the activity log can group them.
        self.session_id = uuid.uuid4().hex
        refresh["sid"] = self.session_id
        self.user = user
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(user).data,
        }


class LogoutSerializer(serializers.Serializer):
    """Blacklist a refresh token on logout."""

    refresh = serializers.CharField()

    def save(self, **kwargs):
        try:
            token = RefreshToken(self.validated_data["refresh"])
            token.blacklist()
        except Exception as exc:  # pragma: no cover - simplejwt raises various
            raise serializers.ValidationError({"detail": "Invalid refresh token."}) from exc
        return None


class UserSerializer(serializers.ModelSerializer):
    """The current user, including what they are allowed to do with money.

    The permission flags are serialized rather than left for the client to
    infer from `role`, so the dashboard hides an action for exactly the same
    reason the API would refuse it. The API is still the authority — these
    only decide what is worth showing.
    """

    role_display = serializers.CharField(source="get_role_display", read_only=True)
    can_record_money = serializers.BooleanField(read_only=True)
    can_forgive_money = serializers.BooleanField(read_only=True)
    can_manage_users = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id", "email", "username", "first_name", "last_name", "date_joined", "last_login",
            "role", "role_display", "is_superuser",
            "can_record_money", "can_forgive_money", "can_manage_users",
        )
        read_only_fields = fields


class ManagedUserSerializer(serializers.ModelSerializer):
    """One account as the Users page lists it."""

    full_name = serializers.SerializerMethodField()
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    status = serializers.CharField(read_only=True)
    invited_by_email = serializers.SerializerMethodField()
    invite_expires_at = serializers.SerializerMethodField()
    is_self = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "email", "first_name", "last_name", "full_name", "role", "role_display",
            "status", "is_superuser", "last_login", "date_joined", "invited_at",
            "invited_by_email", "invite_expires_at", "deactivated_at", "is_self",
        )
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_invited_by_email(self, obj):
        return obj.invited_by.email if obj.invited_by_id and obj.invited_by else None

    def get_invite_expires_at(self, obj):
        if obj.status != "invited":
            return None
        live = [i for i in obj.invites.all() if not i.used]
        return max(i.expires_at for i in live) if live else None

    def get_is_self(self, obj):
        request = self.context.get("request")
        return bool(request and request.user.pk == obj.pk)


class InviteUserSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)


class UpdateUserSerializer(serializers.Serializer):
    role = serializers.CharField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)


class AcceptInviteSerializer(serializers.Serializer):
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=12, trim_whitespace=False)


# ---------------------------------------------------------------------------
# Password Reset Serializers
# ---------------------------------------------------------------------------

class PasswordResetRequestSerializer(serializers.Serializer):
    """Accepts an email address and triggers the reset flow."""
    email = serializers.EmailField()


class ChangePasswordSerializer(serializers.Serializer):
    """Change the password of the signed-in account.

    The current password is required even though the caller is already
    authenticated: a stolen access token should not be enough to take permanent
    ownership of the account.
    """

    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, min_length=12, trim_whitespace=False)

    def validate_current_password(self, value):
        user = self.context["user"]
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        from django.contrib.auth.password_validation import validate_password
        validate_password(value, user=self.context["user"])
        return value

    def validate(self, attrs):
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "The new password must differ from the current one."}
            )
        return attrs


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Accepts a token + new password and completes the reset.

    Field name matches the view/API contract (`new_password`). Password
    strength is enforced via Django's configured validators.
    """
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=12, trim_whitespace=False)

    def validate_new_password(self, value):
        from django.contrib.auth.password_validation import validate_password
        validate_password(value)
        return value
