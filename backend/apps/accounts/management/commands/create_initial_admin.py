"""
Create the initial admin user from environment variables.

Usage (on Render or any environment where createsuperuser is not interactive):

    INITIAL_ADMIN_EMAIL=william@gmail.com \
    INITIAL_ADMIN_USERNAME=owner \
    INITIAL_ADMIN_PASSWORD=SomeStrongPass123! \
    python manage.py create_initial_admin

Idempotent: if a user with that email already exists, the command updates
their password instead of erroring. Password is validated against Django's
standard password validators (min 12 chars, not all numeric, etc.).

After the user is created, remove the INITIAL_ADMIN_* env vars from your
hosting dashboard so they don't sit around as secrets.
"""
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create or reset the initial admin user from INITIAL_ADMIN_* env vars."

    def handle(self, *args, **options):
        email = os.environ.get("INITIAL_ADMIN_EMAIL", "").strip().lower()
        username = os.environ.get("INITIAL_ADMIN_USERNAME", "").strip()
        password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")

        # Skip silently if no env vars are set — makes this safe to leave
        # in the build command permanently. The command only does something
        # on deploys where the INITIAL_ADMIN_* vars are temporarily present.
        if not (email or username or password):
            self.stdout.write(
                self.style.NOTICE(
                    "create_initial_admin: no INITIAL_ADMIN_* env vars set, skipping."
                )
            )
            return

        missing = [
            name for name, val in [
                ("INITIAL_ADMIN_EMAIL", email),
                ("INITIAL_ADMIN_USERNAME", username),
                ("INITIAL_ADMIN_PASSWORD", password),
            ] if not val
        ]
        if missing:
            raise CommandError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        User = get_user_model()

        # Validate password strength against Django's validators.
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(
                f"Password does not meet requirements: {'; '.join(exc.messages)}"
            ) from exc

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": username,
                "is_staff": True,
                "is_superuser": True,
            },
        )

        if not created:
            # Existing user — update username if different, reset password,
            # ensure staff/superuser flags are set.
            user.username = username
            user.is_staff = True
            user.is_superuser = True
            self.stdout.write(
                self.style.WARNING(f"User {email} already exists — resetting password.")
            )

        user.set_password(password)
        user.save()

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} superuser: {email} (username={username})"
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                "Remember to remove INITIAL_ADMIN_* env vars from your hosting "
                "dashboard now that the user has been created."
            )
        )
