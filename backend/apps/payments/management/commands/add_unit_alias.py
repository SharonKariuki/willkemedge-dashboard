"""
Map a payment reference tenants actually type onto the unit it means.

The matcher resolves a bill ref by exact unit label, then by UnitAlias, then
by the zero-padding-insensitive canonical form. Short forms that drop the
building code entirely ("3A" for DON3A) are deliberately NOT guessed — a bare
house number could belong to any building, and guessing misroutes money. They
need an explicit alias, which is what this command creates.

Idempotent: re-running with the same pair is a no-op. An alias that already
points somewhere else is reported and left alone — retargeting money is a
decision, not a side effect, so use --force to say so out loud.

Usage (Render Shell):
    python manage.py add_unit_alias 3A DON3A --note "Donholm short form"
    python manage.py add_unit_alias 3A DON3A --dry-run
    python manage.py add_unit_alias --from-unmatched          # suggest, don't write
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction


class Command(BaseCommand):
    help = "Create a UnitAlias so a legacy/short payment reference matches a unit."

    def add_arguments(self, parser):
        parser.add_argument("alias", nargs="?", help="The reference tenants type, e.g. '3A'.")
        parser.add_argument("unit_label", nargs="?", help="The current unit label, e.g. 'DON3A'.")
        parser.add_argument("--note", default="", help="Why this alias exists.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Validate and report without writing.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Repoint an alias that currently resolves to a different unit.",
        )
        parser.add_argument(
            "--from-unmatched", action="store_true",
            help=(
                "List the bill refs in the UNMATCHED queue that still resolve to "
                "nothing, with the money behind each. Read-only — it suggests "
                "what needs an alias, it never creates one."
            ),
        )

    def handle(self, *args, **opts):
        if opts["from_unmatched"]:
            return self._report_unmatched()

        alias_label = (opts["alias"] or "").strip()
        unit_label = (opts["unit_label"] or "").strip()
        if not alias_label or not unit_label:
            raise CommandError("Both ALIAS and UNIT_LABEL are required (or use --from-unmatched).")

        from apps.buildings.models import Unit, UnitAlias

        unit = Unit.objects.filter(label__iexact=unit_label).select_related("building").first()
        if unit is None:
            raise CommandError(f"No unit has label {unit_label!r}.")

        # Already a real unit label? Then it needs no alias, and UnitAlias.clean
        # would reject it anyway.
        if Unit.objects.filter(label__iexact=alias_label).exists():
            raise CommandError(
                f"{alias_label!r} is already a current unit label — it matches directly, "
                f"no alias needed."
            )

        existing = UnitAlias.objects.filter(label__iexact=alias_label).select_related(
            "unit", "unit__building"
        ).first()
        if existing and existing.unit_id == unit.pk:
            self.stdout.write(f"Alias {alias_label!r} → {unit} already exists — nothing to do.")
            return
        if existing and not opts["force"]:
            raise CommandError(
                f"Alias {alias_label!r} already points to {existing.unit}. "
                f"Re-run with --force to repoint it to {unit}."
            )

        verb = "Would repoint" if existing else "Would create"
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING(f"{verb} {alias_label!r} → {unit} (dry run)."))
            return

        with db_transaction.atomic():
            if existing:
                existing.unit = unit
                existing.note = opts["note"] or existing.note
                try:
                    existing.full_clean()
                except ValidationError as exc:
                    raise CommandError(f"Invalid alias: {exc.message_dict}") from exc
                existing.save(update_fields=["unit", "note"])
                self.stdout.write(self.style.SUCCESS(f"Repointed {alias_label!r} → {unit}."))
            else:
                obj = UnitAlias(label=alias_label, unit=unit, note=opts["note"])
                try:
                    obj.full_clean()
                except ValidationError as exc:
                    raise CommandError(f"Invalid alias: {exc.message_dict}") from exc
                obj.save()
                self.stdout.write(self.style.SUCCESS(f"Created alias {alias_label!r} → {unit}."))

        self.stdout.write(
            "Run `python manage.py reprocess_unmatched_ipn --dry-run` to see what this releases."
        )

    def _report_unmatched(self):
        """Show which bill refs in the queue still resolve to no unit."""
        from apps.payments.coop_ipn import _parse_narration
        from apps.payments.matching import match_tenant, normalize_bill_ref
        from apps.payments.models import CoopIpnEvent, CoopIpnStatus

        events = CoopIpnEvent.objects.filter(status=CoopIpnStatus.UNMATCHED).order_by("received_at")
        unresolved: dict[str, list] = {}
        for event in events:
            parsed = _parse_narration(event.narration or "")
            if any(match_tenant(tok) for tok in parsed["tokens"]):
                continue  # a ref in this narration now resolves — reprocess will clear it
            for token in parsed["tokens"]:
                ref = normalize_bill_ref(token)
                # Keep the ones that look like a house number, drop phones/codes.
                if ref and not ref.isdigit() and len(ref) <= 12:
                    unresolved.setdefault(ref, []).append(event)
                    break

        if not unresolved:
            self.stdout.write(self.style.SUCCESS("No unresolved bill refs in the queue."))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"{len(unresolved)} bill ref(s) in the UNMATCHED queue match no unit:"
        ))
        rows = sorted(unresolved.items(), key=lambda kv: -sum(e.amount for e in kv[1]))
        for ref, evs in rows:
            total = sum(e.amount for e in evs)
            self.stdout.write(
                f"  {ref:<12} KES {total:>12,.2f}  ({len(evs)} payment(s))"
            )
        self.stdout.write("")
        self.stdout.write(
            "Confirm what each one means, then: python manage.py add_unit_alias <ref> <UNIT>"
        )
