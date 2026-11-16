"""Users page API: invite people, change their role, switch accounts off.

    GET    /api/auth/users/                   everyone, with status
    POST   /api/auth/users/                   invite {email, role, first_name, last_name}
    PATCH  /api/auth/users/{id}/              {role?, first_name?, last_name?}
    POST   /api/auth/users/{id}/resend/       a fresh invite link
    POST   /api/auth/users/{id}/deactivate/   switch off now; sessions revoked
    POST   /api/auth/users/{id}/reactivate/   switch back on

    GET    /api/auth/invite/{token}/          public: who the link is for
    POST   /api/auth/invite/accept/           public: {token, new_password}

The rules live in ``user_admin``; these views only translate.
"""
from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from . import access, user_admin
from .models import Role, User
from .serializers import (
    AcceptInviteSerializer,
    InviteUserSerializer,
    ManagedUserSerializer,
    UpdateUserSerializer,
)


class CanManageUsers(BasePermission):
    message = "Only the owner or the superadmin can manage users."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and access.has_capability(request.user, access.Cap.MANAGE_USERS))


def _refused(exc: user_admin.UserAdminError) -> Response:
    code = status.HTTP_403_FORBIDDEN if isinstance(exc, user_admin.NotAllowed) else status.HTTP_400_BAD_REQUEST
    return Response({"detail": str(exc)}, status=code)


def _users():
    return (
        User.objects.select_related("invited_by").prefetch_related("invites", "buildings")
        # Superadmin and owners first, then the rest by name.
        .annotate(rank=Case(When(is_superuser=True, then=Value(0)),
                            When(role=Role.OWNER, then=Value(1)), default=Value(2),
                            output_field=IntegerField()))
        .order_by("rank", "first_name", "email")
    )


class UserListView(APIView):
    permission_classes = [CanManageUsers]

    def get(self, request):
        data = ManagedUserSerializer(_users(), many=True, context={"request": request}).data
        roles = [{"value": r, "label": Role(r).label} for r in user_admin.assignable_roles(request.user)]
        grantable = access.grantable(request.user)
        return Response({
            "users": data,
            "assignable_roles": roles,
            # Everything the Access dialog needs to draw the checklist the
            # same way the API will judge it.
            "permissions": [
                {"value": cap, "area": area, "label": label, "hint": hint,
                 "requires": sorted(access.REQUIRES.get(cap, ())), "grantable": cap in grantable}
                for cap, area, label, hint in access.PERMISSIONS
            ],
            "role_capabilities": {r: sorted(caps) for r, caps in access.ROLE_CAPABILITIES.items()},
            "scoped_roles": sorted(access.SCOPED_ROLES),
        })

    def post(self, request):
        s = InviteUserSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user = user_admin.invite(request.user, **s.validated_data)
        except user_admin.UserAdminError as exc:
            return _refused(exc)
        # The invite is saved; the email is a separate step that can fail on
        # its own. Say so rather than erroring - Resend can try again.
        email_error = user_admin.email_invite(user)
        data = ManagedUserSerializer(_users().get(pk=user.pk), context={"request": request}).data
        return Response({**data, "email_error": email_error}, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    permission_classes = [CanManageUsers]

    def patch(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        s = UpdateUserSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user_admin.update(request.user, target, **s.validated_data)
        except user_admin.UserAdminError as exc:
            return _refused(exc)
        return Response(ManagedUserSerializer(_users().get(pk=pk), context={"request": request}).data)


class UserActionView(APIView):
    permission_classes = [CanManageUsers]
    ACTIONS = {
        "resend": user_admin.resend,
        "deactivate": user_admin.deactivate,
        "reactivate": user_admin.reactivate,
    }

    def post(self, request, pk, action):
        if action not in self.ACTIONS:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        target = get_object_or_404(User, pk=pk)
        try:
            self.ACTIONS[action](request.user, target)
        except user_admin.UserAdminError as exc:
            return _refused(exc)
        target.refresh_from_db()
        # Resend always issues a new link; switching back on an account that
        # never accepted its invite does too.
        email_error = user_admin.email_invite(target) if target.status == "invited" else None
        data = ManagedUserSerializer(_users().get(pk=pk), context={"request": request}).data
        return Response({**data, "email_error": email_error})


class InviteDetailView(APIView):
    """Public. What the set-password page shows, or 404 for a dead link."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        link = user_admin.open_invite(token)
        if link is None:
            return Response({"detail": "This invite link is invalid or has expired."},
                            status=status.HTTP_404_NOT_FOUND)
        user = link.user
        return Response({
            "email": user.email,
            "first_name": user.first_name,
            "role_display": user.get_role_display(),
            "expires_at": link.expires_at,
        })


class InviteAcceptView(APIView):
    """Public. Choose a password; the account switches on."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        s = AcceptInviteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user = user_admin.accept(s.validated_data["token"], s.validated_data["new_password"])
        except user_admin.UserAdminError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Your account is ready. Sign in with your new password.",
                         "email": user.email})
