"""
Re-run the matcher over every UNMATCHED CoopIpnEvent.

The system marks an event UNMATCHED the moment it arrives if no tenant
can be found. But if the missing master data is added later (e.g. you
seed a building and its tenants), those old events stay UNMATCHED — they
don't get re-processed automatically.

This command walks through every event whose status is UNMATCHED, re-runs
the parser + matcher against the current database, and:

  - **Confident bill-ref match** → allocates the payment (arrears-first),
    flips status to RECORDED, links the Payment, queues the receipt.
  - **Phone-only / name-only match** → keeps UNMATCHED but refreshes the
    `detail` so the admin sees "Low-confidence match (phone)" with the
    candidate tenant — one click to confirm in admin.
  - **No match at all** → leaves the event unchanged.

Idempotent and safe to re-run.

Usage (Render Shell):
    python manage.py reprocess_unmatched_ipn
    python manage.py reprocess_unmatched_ipn --dry-run    # preview only
"""
from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.db import transaction as db_transaction


class Command(BaseCommand):
    help = "Re-run the matcher on UNMATCHED Co-op IPN events (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be matched without changing any records.",
        )
        parser.add_argument(
            "--auto-confirm",
            action="store_true",
            help=(
                "Also auto-record events where ONLY the payer phone matched "
                "an active tenant. USE WITH CARE — bypasses the manual "
                "confirmation step on phone-only matches. Wrong matches "
                "(e.g. a relative paying from another tenant's phone) can "
                "still be reversed via the admin reversal flow, but you "
                "trade the per-event safety check for speed."
            ),
        )

    def handle(self, *args, **opts):
        from apps.payments.coop_ipn import (
            _parse_narration,
            _posting_date,
            _resolve_tenant,
            _safe_enqueue,
        )
        from apps.payments.models import CoopIpnEvent, CoopIpnStatus
        from apps.payments.services import allocate_payment_fifo
        from apps.payments.tasks import send_deposit_receipt

        dry = opts["dry_run"]
        auto = opts["auto_confirm"]
        events = CoopIpnEvent.objects.filter(status=CoopIpnStatus.UNMATCHED).order_by("received_at")
        total = events.count()
        suffix = ""
        if auto:
            suffix += " — auto-confirming phone matches"
        if dry:
            suffix += " — dry run"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Reprocessing {total} unmatched event(s){suffix}"
        ))

        recorded = auto_recorded = low_conf = still_unmatched = errored = 0

        for event in events:
            payload = event.raw_payload or {}
            parsed = _parse_narration(event.narration or "")
            try:
                tenant, matched_by, confident = _resolve_tenant(payload, parsed)
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(
                    f"  #{event.pk} {event.transaction_id} — matcher error: {exc}"
                ))
                errored += 1
                continue

            if not tenant:
                still_unmatched += 1
                self.stdout.write(
                    f"  #{event.pk} {event.transaction_id} KES {event.amount} — no match"
                )
                continue

            # When --auto-confirm is set, treat phone matches as confident.
            effective_confident = confident or auto

            if not effective_confident:
                # Phone-only → refresh detail, keep UNMATCHED for admin confirm.
                new_detail = f"Low-confidence match: {tenant} ({matched_by}) — verify in admin"
                self.stdout.write(self.style.WARNING(
                    f"  #{event.pk} {event.transaction_id} KES {event.amount} → "
                    f"LOW-CONFIDENCE: {tenant} ({matched_by})"
                ))
                if not dry:
                    event.detail = new_detail[:255]
                    event.save(update_fields=["detail"])
                low_conf += 1
                continue

            # Will be recorded.
            tag = "AUTO-RECORD" if (not confident and auto) else "RECORD"
            style = self.style.NOTICE if tag == "AUTO-RECORD" else self.style.SUCCESS
            self.stdout.write(style(
                f"  #{event.pk} {event.transaction_id} KES {event.amount} → "
                f"{tag}: {tenant} ({matched_by})"
            ))
            if dry:
                if not confident:
                    auto_recorded += 1
                else:
                    recorded += 1
                continue

            try:
                with db_transaction.atomic():
                    pay_date = _posting_date(payload)
                    is_auto = (not confident) and auto
                    notes = (
                        f"Reprocessed from unmatched queue; matched by {matched_by} "
                        f"({'auto-confirmed phone' if is_auto else 'bill_ref'}); "
                        f"ref {event.payment_ref}"
                    )
                    payments = allocate_payment_fifo(
                        tenant=tenant,
                        amount=event.amount,
                        payment_date=pay_date,
                        source=parsed["channel"],
                        reference=event.transaction_id,
                        notes=notes,
                    )
                    event.status = CoopIpnStatus.RECORDED
                    split = f" across {len(payments)} periods" if len(payments) > 1 else ""
                    prefix = "Auto-confirmed" if is_auto else "Reprocessed"
                    event.detail = f"{prefix} — matched by {matched_by}{split}"[:255]
                    event.payment = payments[0]
                    event.save(update_fields=["status", "detail", "payment"])
                _safe_enqueue(
                    send_deposit_receipt,
                    tenant.id, str(event.amount), event.transaction_id, pay_date.isoformat(),
                )
                if is_auto:
                    auto_recorded += 1
                else:
                    recorded += 1
            except IntegrityError as exc:
                self.stdout.write(self.style.ERROR(
                    f"    DB error on #{event.pk}: {exc}"
                ))
                errored += 1
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(
                    f"    Error allocating #{event.pk}: {exc}"
                ))
                errored += 1

        self.stdout.write("")
        parts = [
            f"{recorded} recorded (bill-ref match)",
        ]
        if auto:
            parts.append(f"{auto_recorded} auto-recorded (phone match)")
        parts.append(f"{low_conf} low-confidence (need admin click)")
        parts.append(f"{still_unmatched} still unmatched")
        parts.append(f"{errored} errored")
        self.stdout.write(self.style.SUCCESS(
            f"Summary ({'dry-run' if dry else 'committed'}): " + ", ".join(parts) + "."
        ))
