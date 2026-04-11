"""
Management command: register M-Pesa C2B URLs with Daraja.

Usage:
    python manage.py register_mpesa_urls

Run once after deployment or whenever the callback URLs change.
"""
from django.core.management.base import BaseCommand

from apps.payments.mpesa import daraja


class Command(BaseCommand):
    help = "Register M-Pesa C2B Validation and Confirmation URLs with Daraja."

    def handle(self, *args, **options):
        self.stdout.write("Registering C2B URLs with Daraja...")
        try:
            result = daraja.register_c2b_urls()
            self.stdout.write(self.style.SUCCESS(f"Success: {result}"))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Failed: {exc}"))
