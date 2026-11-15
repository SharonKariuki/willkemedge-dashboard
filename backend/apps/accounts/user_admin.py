"""Who may add, change and switch off dashboard accounts - and how.

Nobody signs themselves up. The owner (the director) or the superadmin invites
a person by email with a role; the account is created switched off and the
person receives a single-use link to choose their own password. Nobody else
ever knows it.

The rules, in one place so the API and the tests read the same ones:

* only the owner and the superadmin manage users;
* the owner may give any role except owner - making another director, and
  anything touching the superadmin or another director, is the superadmin's;
* nobody changes or switches off their own account here, so nobody can lock
  themselves out by mistake;
* switching an account off is immediate: the next request it makes is refused
  (simplejwt rejects inactive users) and every saved sign-in is revoked.
  Accounts are never deleted - the activity log and the payments they recorded
  still name them.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from . import audit
from .models import AccountInvite, Role, User


class UserAdminError(Exception):
    """A request the rules refuse; the message is shown to the person."""


class NotAllowed(UserAdminError):
    """The actor may not do this to this account."""


def assignable_roles(actor: User) -> list[str]:
    if actor.is_superuser:
        return [r.value for r in Role]
    if actor.can_manage_users:
        return [r.value for r in Role if r != Role.OWNER]
    return []


def _check_role(actor: User, role: str) -> None:
    if role not in Role.values:
        raise UserAdminError(f"Unknown role {role!r}.")
    if role not in assignable_roles(actor):
        raise NotAllowed("Only the superadmin can make someone an owner/director.")


def _check_target(actor: User, target: User) -> None:
    if not actor.can_manage_users:
        raise NotAllowed("Only the owner or the superadmin can manage users.")
    if target.pk == actor.pk:
        raise NotAllowed("You can't change or switch off your own account here.")
    if not actor.is_superuser and (target.is_superuser or target.role == Role.OWNER):
        raise NotAllowed("Only the superadmin can change an owner/director or the superadmin account.")


def _revoke_sessions(user: User) -> None:
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)


def _send(invite: AccountInvite) -> None:
    from .tasks import send_invite_email

    transaction.on_commit(lambda: send_invite_email.delay(invite.pk))


@transaction.atomic
def invite(actor: User, *, email: str, role: str, first_name: str = "", last_name: str = "") -> User:
    if not actor.can_manage_users:
        raise NotAllowed("Only the owner or the superadmin can manage users.")
    email = (email or "").strip().lower()
    if not email:
        raise UserAdminError("Enter an email address.")
    _check_role(actor, role)
    existing = User.objects.filter(email__iexact=email).first()
    if existing:
        if existing.status == "invited":
            raise UserAdminError(f"{email} has already been invited. Use Resend invite instead.")
        raise UserAdminError(f"{email} already has an account.")

    now = timezone.now()
    user = User(
        email=email, username=email[:150], role=role,
        first_name=first_name.strip()[:150], last_name=last_name.strip()[:150],
        is_active=False, invited_by=actor, invited_at=now,
    )
    user.set_unusable_password()
    user.save()
    link = AccountInvite.issue(user, created_by=actor)
    _send(link)
    audit.record(
        action="user.invite", object_type="user", object_id=user.pk, object_label=email,
        summary=f"Invited {email} as {user.get_role_display()}", actor=actor,
        new_values={"email": email, "role": role}, is_financial=False,
    )
    return user


@transaction.atomic
def resend(actor: User, target: User) -> AccountInvite:
    _check_target(actor, target)
    if target.status != "invited":
        raise UserAdminError("Only an invite that hasn't been accepted can be re-sent.")
    link = AccountInvite.issue(target, created_by=actor)
    target.invited_at = timezone.now()
    target.save(update_fields=["invited_at"])
    _send(link)
    audit.record(
        action="user.invite_resend", object_type="user", object_id=target.pk, object_label=target.email,
        summary=f"Re-sent the invite to {target.email}", actor=actor, is_financial=False,
    )
    return link


@transaction.atomic
def update(actor: User, target: User, *, role: str | None = None,
           first_name: str | None = None, last_name: str | None = None) -> User:
    _check_target(actor, target)
    old = {"role": target.role, "first_name": target.first_name, "last_name": target.last_name}
    if role is not None and role != target.role:
        _check_role(actor, role)
        target.role = role
    if first_name is not None:
        target.first_name = first_name.strip()[:150]
    if last_name is not None:
        target.last_name = last_name.strip()[:150]
    new = {"role": target.role, "first_name": target.first_name, "last_name": target.last_name}
    if new != old:
        target.save(update_fields=["role", "first_name", "last_name"])
        audit.record(
            action="user.update", object_type="user", object_id=target.pk, object_label=target.email,
            summary=(f"Changed {target.email}'s role to {target.get_role_display()}"
                     if new["role"] != old["role"] else f"Updated {target.email}'s name"),
            actor=actor, old_values=old, new_values=new, is_financial=False,
        )
    return target


@transaction.atomic
def deactivate(actor: User, target: User) -> User:
    _check_target(actor, target)
    if target.deactivated_at:
        return target
    target.is_active = False
    target.deactivated_at = timezone.now()
    target.save(update_fields=["is_active", "deactivated_at"])
    AccountInvite.objects.filter(user=target, used=False).update(used=True)
    _revoke_sessions(target)
    audit.record(
        action="user.deactivate", object_type="user", object_id=target.pk, object_label=target.email,
        summary=f"Switched off {target.email}'s account", actor=actor, is_financial=False,
    )
    return target


@transaction.atomic
def reactivate(actor: User, target: User) -> User:
    _check_target(actor, target)
    if not target.deactivated_at:
        return target
    target.deactivated_at = None
    if target.invited_at and not target.invite_accepted_at:
        # They never chose a password: back to "invited", with a fresh link.
        target.is_active = False
        target.save(update_fields=["is_active", "deactivated_at"])
        link = AccountInvite.issue(target, created_by=actor)
        target.invited_at = timezone.now()
        target.save(update_fields=["invited_at"])
        _send(link)
    else:
        target.is_active = True
        target.save(update_fields=["is_active", "deactivated_at"])
    audit.record(
        action="user.reactivate", object_type="user", object_id=target.pk, object_label=target.email,
        summary=f"Switched {target.email}'s account back on", actor=actor, is_financial=False,
    )
    return target


def open_invite(token: str) -> AccountInvite | None:
    """The invite behind a link, if it can still be used."""
    link = AccountInvite.objects.select_related("user").filter(token=(token or "").strip()).first()
    return link if link and link.is_valid else None


@transaction.atomic
def accept(token: str, password: str) -> User:
    """Set the invited person's password and switch the account on."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    link = open_invite(token)
    if link is None:
        raise UserAdminError("This invite link is invalid or has expired. Ask for a new one.")
    user = link.user
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        raise UserAdminError(" ".join(exc.messages)) from exc
    user.set_password(password)
    user.is_active = True
    user.invite_accepted_at = timezone.now()
    user.save(update_fields=["password", "is_active", "invite_accepted_at"])
    link.used = True
    link.save(update_fields=["used"])
    audit.record(
        kind="auth", action="auth.invite_accepted", object_type="user", object_id=user.pk,
        object_label=user.email, summary="Accepted the invite and set a password",
        actor=user, is_financial=False,
    )
    return user
