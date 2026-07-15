"""
Batch-generate official rent-statement PDFs from a JSON file.

    python manage.py generate_statements tenants.json --out ./statements

The JSON may be a single tenant object, a list of tenants, or
``{"tenants": [ ... ]}``. One PDF per tenant is written as ``Unit <unit>.pdf``.

Each tenant object follows the shape documented in
``apps.payments.statement_generator`` — running balances, water charges,
arrears, current month, and total due are all computed, not trusted from input.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.payments.statement_generator import generate_statement_file


class Command(BaseCommand):
    help = "Generate official rent-statement PDFs from a JSON file (one per tenant)."

    def add_arguments(self, parser):
        parser.add_argument("json_path", help="Path to the tenant JSON file.")
        parser.add_argument("--out", default="statements",
                            help="Output directory for the PDFs (default: ./statements).")

    def handle(self, *args, **opts):
        path = Path(opts["json_path"])
        if not path.exists():
            raise CommandError(f"JSON file not found: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON: {exc}") from exc

        if isinstance(payload, dict) and "tenants" in payload:
            tenants = payload["tenants"]
        elif isinstance(payload, dict):
            tenants = [payload]
        elif isinstance(payload, list):
            tenants = payload
        else:
            raise CommandError("JSON must be an object, a list, or {'tenants': [...]}.")

        out_dir = Path(opts["out"])
        written, failed = 0, 0
        for tenant in tenants:
            unit = tenant.get("unit", "?")
            try:
                dest = generate_statement_file(tenant, out_dir)
                self.stdout.write(f"  {dest.name}")
                written += 1
            except Exception as exc:  # keep going so one bad row doesn't stop the batch
                self.stderr.write(self.style.WARNING(f"  ! Unit {unit}: {exc}"))
                failed += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n{written} statement(s) written to {out_dir}/"
            + (f", {failed} failed." if failed else ".")
        ))
