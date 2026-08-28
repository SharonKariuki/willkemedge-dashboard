"""
Apply Dr Osoro's answers on the Matasia Commercial queries (Aug 2026).

Four of the questions raised against the 21 Aug 2026 statement came back
answered. Three of them change data:

  MCF04  vacant — the roster had Wilkem Ventures Co. Ltd. recorded as an
         active tenancy at 25,000 a month. It was never billed and never paid
         anything, so the tenancy is archived and the unit returned to vacant.

  MCF20  vacant — the unit is on the statement but has never existed in the
         system. Created as a vacant BUSINESS shop on the first floor, matching
         its neighbours.

  MCF12  Sidai paid the 58,760 by CHEQUE, not bank transfer.
  MCG02  Glow by Ellie paid the 22,500 in CASH, not M-Pesa.

Both payments were entered from the statement with a guessed channel, because
neither had reached the Co-op feed. Payments are immutable, so the correction
is a void plus a re-record rather than an edit — the reversal and the
replacement both stay in the ledger.

  MCG02  no VAT is charged — confirmed deliberate, so nothing to do. The
         August row already carries 22,500 with zero VAT.

STILL UNRESOLVED, deliberately not touched: the answer names MCF07 as newly
occupied by Ignite Energy Access Limited, while the roster has them on MCG07
with 180,000 across three periods. Ground floor and first floor are different
units and different payment references, so moving that tenancy is not a guess
worth making. See --report.

DRY-RUN BY DEFAULT. Nothing is written without --apply. Re-running is safe.

Usage:
    python manage.py apply_matasia_answers
    python manage.py apply_matasia_answers --apply
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Tenancies the landlord has confirmed do not exist — (unit, tenant id, why)
VACATE = [
    ("MCF04", 165, "Dr Osoro confirms MCF04 is vacant"),
]

# Units on the statement that the system has never had — (unit, floor, type)
CREATE_UNITS = [
    ("MCF20", "MC", 1, "shop"),
]

# Payments entered from the statement with a guessed channel —
# (idempotency key, unit, tenant id, correct source, what the landlord said)
CHANNELS = [
    ("STMT-2026-08-MCF12", "MCF12", 166, "cheque", "Sidai paid by cheque"),
    ("STMT-2026-08-MCG02", "MCG02", 150, "cash", "Glow by Ellie paid cash"),
]

# Reported every run so it is not quietly forgotten.
UNRESOLVED = [
    (
        "MCF07 / MCG07 — Ignite Energy Access Limited",
        "The answer names MCF07 as newly occupied. The roster has Ignite on MCG07 "
        "with 3 payments totalling 180,000 and 3 arrears rows. MCF07 exists and is "
        "vacant. Confirm which unit before moving the tenancy — the unit label is "
        "the payment reference tenants quote.",
    ),
]


class Command(BaseCommand):
    help = (
        "Apply Dr Osoro's answers on the Matasia Commercial queries: vacate MCF04, "
        "create MCF20, and correct two payment channels. Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def _head(self, text):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{text}"))

    def _do(self, text):
        self.stdout.write(f"  {text}")
        self.changes += 1

    def _skip(self, text):
        self.stdout.write(self.style.WARNING(f"  skip  {text}"))

    def handle(self, *args, **opts):
        from apps.buildings.models import Building, Unit, UnitStatus
        from apps.payments.models import Payment
        from apps.tenants.models import Tenant, TenantStatus

        self.apply = opts["apply"]
        self.changes = 0

        def resolve(tid, label):
            t = Tenant.objects.filter(pk=tid).select_related("unit").first()
            if t is None:
                return None, f"tenant #{tid} not found"
            actual = t.unit.label if t.unit else "(no unit)"
            if actual.upper() != label.upper():
                return None, f"#{tid} is '{t.full_name}' on {actual}, expected {label}"
            return t, None

        # -- pre-flight ------------------------------------------------------
        wrong = []
        for label, tid, _why in VACATE:
            _t, problem = resolve(tid, label)
            if problem and "not found" not in problem:
                wrong.append(problem)
        for _key, label, tid, _src, _why in CHANNELS:
            _t, problem = resolve(tid, label)
            if problem and "not found" not in problem:
                wrong.append(problem)
        if wrong:
            raise CommandError(
                "Pre-flight failed — tenant ids do not match their units:\n  "
                + "\n  ".join(wrong)
                + "\n\nPrimary keys are not portable between databases. Nothing was written."
            )

        # -- 1. Vacate -------------------------------------------------------
        self._head("1. Tenancies the landlord confirms do not exist")
        for label, tid, why in VACATE:
            t, problem = resolve(tid, label)
            if problem:
                self._skip(f"{label}: {problem}")
                continue
            if t.status == TenantStatus.ARCHIVED:
                self._skip(f"{label} {t.full_name}: already archived")
                continue
            live = Payment.objects.filter(tenant=t, voided_at__isnull=True).count()
            if live:
                self._skip(
                    f"{label} {t.full_name}: has {live} live payment(s) — refusing to "
                    f"archive a tenancy that holds money"
                )
                continue
            self._do(f"{label} {t.full_name}: archived, unit -> vacant  ({why})")
            if self.apply:
                with transaction.atomic():
                    t.status = TenantStatus.ARCHIVED
                    t.move_out_date = t.move_out_date or _dt.date(2026, 8, 21)
                    t.notes = (t.notes + f"\nArchived by apply_matasia_answers: {why}.").strip()
                    t.save(update_fields=["status", "move_out_date", "notes", "updated_at"])
                    unit = t.unit
                    unit.status = UnitStatus.VACANT
                    unit.monthly_rent = Decimal("0.00")
                    unit.save(update_fields=["status", "monthly_rent", "updated_at"])

        # -- 2. Create missing units ------------------------------------------
        self._head("2. Units on the statement that the system never had")
        for label, building_code, floor, unit_type in CREATE_UNITS:
            if Unit.objects.filter(label__iexact=label).exists():
                self._skip(f"{label}: already exists")
                continue
            building = Building.objects.filter(code=building_code).first()
            if building is None:
                self._skip(f"{label}: no building with code {building_code}")
                continue
            self._do(f"{label}: created as a vacant {unit_type} on floor {floor}")
            if self.apply:
                Unit.objects.create(
                    building=building, label=label, floor=floor, unit_type=unit_type,
                    classification="BUSINESS", monthly_rent=Decimal("0.00"),
                    status=UnitStatus.VACANT,
                    notes="Created from the 21 Aug 2026 statement; confirmed vacant.",
                )

        # -- 3. Payment channels ----------------------------------------------
        self._head("3. Payment channels the landlord has now confirmed")
        for key, label, tid, source, why in CHANNELS:
            t, problem = resolve(tid, label)
            if problem:
                self._skip(f"{label}: {problem}")
                continue
            pay = Payment.objects.filter(
                tenant=t, idempotency_key=key, voided_at__isnull=True
            ).first()
            if pay is None:
                self._skip(f"{label}: no live payment under {key}")
                continue
            if pay.source == source:
                self._skip(f"{label} {t.full_name}: already recorded as {source}")
                continue
            self._do(f"{label} {t.full_name}: {pay.amount} {pay.source} -> {source}  ({why})")
            if self.apply:
                self._recut(pay, t, source, why)

        # -- 4. Still open ------------------------------------------------------
        self._head("4. Answered but not actionable without a further confirmation")
        for title, detail in UNRESOLVED:
            self.stdout.write(self.style.NOTICE(f"  {title}"))
            self.stdout.write(f"      {detail}")

        if not self.apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {self.changes} change(s) would be written. Re-run with --apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nApplied {self.changes} change(s)."))

    def _recut(self, payment, tenant, source, why):
        """Void the mis-channelled payment and re-record it on the right one.

        Payments are immutable financial records, so the channel is corrected by
        reversing the original and writing a replacement — both stay visible in
        the ledger — rather than editing the row underneath the audit trail.
        """
        from apps.payments.services import process_payment, void_payment

        amount, date = payment.amount, payment.payment_date
        month, year = payment.period_month, payment.period_year
        key, ref, notes = payment.idempotency_key, payment.reference, payment.notes

        with transaction.atomic():
            void_payment(payment, reason=f"Re-recorded as {source} — {why}"[:255])
            process_payment(
                tenant=tenant, amount=amount, payment_date=date,
                period_month=month, period_year=year, source=source,
                reference=ref, idempotency_key=f"{key}-{source}",
                notes=(f"{notes}\nChannel corrected to {source}: {why}.").strip(),
            )
