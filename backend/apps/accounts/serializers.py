"""Auth serializers."""
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

    class Meta:
        model = User
        fields = (
            "id", "email", "username", "date_joined", "last_login",
            "role", "role_display", "can_record_money", "can_forgive_money",
        )
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Password Reset Serializers
# ---------------------------------------------------------------------------

class PasswordResetRequestSerializer(serializers.Serializer):
    """Accepts an email address and triggers the reset flow."""
    email = serializers.EmailField()


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
