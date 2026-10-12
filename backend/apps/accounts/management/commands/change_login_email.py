"""
Change the login email of an existing dashboard account.

Email is the USERNAME_FIELD, so this *is* the login identity: after the
change the account signs in with the new address and the SAME password.
The password hash is never read, written or reset by this command.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe:
once the account carries the new address, a second run reports "already set"
and exits cleanly, so it is harmless to leave in a deploy step.

Usage:
    python manage.py change_login_email \
        --from william@gmail.com --to owner.personal@gmail.com
    python manage.py change_login_email \
        --from william@gmail.com --to owner.personal@gmail.com --apply

Never point a login at EMAIL_HOST_USER (wilkem.ventures@gmail.com). The app
holds that mailbox's app password, which reads IMAP as well as sending SMTP,
so anyone who can read the env vars could open the reset link and take the
account.

If --from is omitted the command targets the single superuser, and refuses
to guess when there is more than one.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


class Command(BaseCommand):
    help = "Point an existing account at a new login email. Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="old_email",
            default="",
            help="Current login email. Defaults to the only superuser.",
        )
        parser.add_argument(
            "--to",
            dest="new_email",
            required=True,
            help="New login email.",
        )
        parser.add_argument("--apply", action="store_true", help="Write the change.")

    def handle(self, *args, **options):
        User = get_user_model()
        old_email = options["old_email"].strip().lower()
        new_email = options["new_email"].strip().lower()
        apply = options["apply"]

        try:
            validate_email(new_email)
        except ValidationError as exc:
            raise CommandError(f"--to is not a valid email: {'; '.join(exc.messages)}") from exc

        user = self._target(User, old_email)

        if user.email == new_email:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Login email is already {new_email} — nothing to do."
                )
            )
            return

        # Unique constraint on email: a collision would fail mid-save, so
        # name the conflicting account instead of leaving a traceback.
        clash = User.objects.filter(email=new_email).exclude(pk=user.pk).first()
        if clash:
            raise CommandError(
                f"{new_email} already belongs to another account "
                f"(id={clash.pk}, username={clash.username!r}). "
                "Delete or rename that account first."
            )

        self.stdout.write(
            f"{user.email} -> {new_email} "
            f"(id={user.pk}, username={user.username!r}, role={user.role})"
        )
        self.stdout.write("Password is untouched — the account keeps its current one.")

        if not apply:
            self.stdout.write(
                self.style.WARNING("Dry run — nothing written. Re-run with --apply.")
            )
            return

        user.email = new_email
        user.save(update_fields=["email"])
        self.stdout.write(self.style.SUCCESS(f"Login email is now {new_email}."))

    def _target(self, User, old_email):
        """The account to rename: the one named by --from, else the superuser."""
        if old_email:
            user = User.objects.filter(email=old_email).first()
            if not user:
                raise CommandError(f"No account with email {old_email}.")
            return user

        supers = list(User.objects.filter(is_superuser=True)[:2])
        if not supers:
            raise CommandError("No superuser found — pass --from explicitly.")
        if len(supers) > 1:
            raise CommandError(
                "More than one superuser — pass --from to say which to change."
            )
        return supers[0]
