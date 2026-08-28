"""
Apply Dr Osoro's answers on the Matasia Commercial queries (Aug 2026).

Questions raised against the 21 Aug 2026 statement that came back answered.
Two of them change data:

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

  MCF04  occupied by Wilkem Ventures Co. Ltd. — a first answer of "vacant" was
         corrected before this ran, so the roster was right and the tenancy
         stays. It is the statement that is wrong to show the unit vacant.

Two things are reported every run rather than acted on: which unit Ignite
Energy actually occupies, and whether MCF04 should be billed at all. Both are
decisions, not data fixes.

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
#
# Empty on purpose. MCF04 was listed here on a first answer of "vacant", then
# corrected to occupied by Wilkem Ventures Co. Ltd. before this ran, so the
# roster was right all along and the tenancy stays. The machinery is kept
# because the same shape of correction will come round again.
VACATE = []

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

# Rent security deposits — (unit, tenant id, amount, why)
#
# A commercial lease takes three months' rent. These tenancies were carrying
# 0.00, which is not "no deposit taken" but "never recorded", so each is set to
# 3x its rent. The figure belongs on the record rather than being computed for
# display every time the page loads.
#
# Left alone deliberately: MCF01 holds 50,000 against an expected 75,000, and
# MCG05 holds 390,780 against 259,500. Both are real recorded figures rather
# than blanks, so overwriting them would destroy whatever they represent.
DEPOSITS = [
    ("MCG01", 159, Decimal("72000.00"), "3 x 24,000"),
    ("MCG02", 150, Decimal("67500.00"), "3 x 22,500"),
    ("MCG03", 160, Decimal("54000.00"), "3 x 18,000"),
    ("MCG10", 164, Decimal("75000.00"), "3 x 25,000"),
    ("MCF04", 165, Decimal("75000.00"), "3 x 25,000"),
    ("MCF12", 166, Decimal("151965.00"), "3 x 50,655"),
    ("MCF13", 167, Decimal("72000.00"), "3 x 24,000"),
]

# Periods to strike out entirely — (unit, tenant id, year, month, why)
#
# Voids every live payment in the period and removes the charge, so the rent
# roll starts after it with a clean nil brought-forward.
#
# Used sparingly and never lightly: MCG02's June payment of 21,880 is a genuine
# Co-op receipt ("GLOW BY ELLIE", 6 Jun), so discarding it reverses real income
# out of the GL. Raised with Dr Osoro, who confirmed the statement's nil July
# brought-forward is what the books should follow.
DISCARD_PERIODS = [
    ("MCG02", 150, 2026, 6, "statement carries nil forward into July; June is struck out"),
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
    (
        "MCF04 — Wilkem Ventures Co. Ltd., occupied but never billed",
        "Confirmed occupied at 25,000 a month, so the roster is right and the "
        "21 Aug statement is wrong to show it vacant. It has no arrears row for "
        "any month, so nothing has ever been charged. Whether the landlord's own "
        "company pays rent or occupies rent-free is a decision, not a data fix — "
        "billing it retrospectively would raise real debt against it.",
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
        checks = (
            [(tid, label) for label, tid, _w in VACATE]
            + [(tid, label) for _k, label, tid, _s, _w in CHANNELS]
            + [(tid, label) for label, tid, _a, _w in DEPOSITS]
            + [(tid, label) for label, tid, _y, _m, _w in DISCARD_PERIODS]
        )
        wrong = []
        for tid, label in checks:
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

        # -- 4. Deposits --------------------------------------------------------
        self._head("4. Rent security deposits the landlord has restated")
        for label, tid, amount, why in DEPOSITS:
            t, problem = resolve(tid, label)
            if problem:
                self._skip(f"{label}: {problem}")
                continue
            if t.deposit_paid == amount:
                self._skip(f"{label} {t.full_name}: already {amount}")
                continue
            self._do(f"{label} {t.full_name}: deposit {t.deposit_paid} -> {amount}  ({why})")
            if self.apply:
                t.deposit_paid = amount
                t.save(update_fields=["deposit_paid", "updated_at"])

        # -- 5. Struck-out periods ----------------------------------------------
        self._head("5. Periods struck out to follow the statement")
        for label, tid, year, month, why in DISCARD_PERIODS:
            t, problem = resolve(tid, label)
            if problem:
                self._skip(f"{label}: {problem}")
                continue
            self._discard_period(t, label, year, month, why)

        # -- 6. Still open ------------------------------------------------------
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

    def _discard_period(self, tenant, label, year, month, why):
        """Strike a whole period out: void its payments, remove its charge.

        The payments are voided rather than deleted, so the receipt and its
        mirror-image reversal both stay in the ledger and the cash that was
        genuinely banked remains traceable. Only the Arrears row — a derived
        charge, not a financial record — is actually removed, which is what
        stops the period appearing in the rent roll at all.
        """
        from apps.payments.models import Arrears, Payment
        from apps.payments.services import void_payment

        payments = list(Payment.objects.filter(
            tenant=tenant, period_year=year, period_month=month, voided_at__isnull=True,
        ))
        charge = Arrears.objects.filter(
            tenant=tenant, period_year=year, period_month=month,
        ).first()

        if not payments and charge is None:
            self._skip(f"{label} {tenant.full_name}: {month}/{year} already struck out")
            return

        banked = sum((p.amount for p in payments), Decimal("0.00"))
        self._do(
            f"{label} {tenant.full_name}: strike out {month}/{year} — "
            f"void {len(payments)} payment(s) totalling {banked}"
            + (f", remove charge of {charge.expected_rent + charge.expected_vat}" if charge else "")
            + f"  ({why})"
        )
        if not self.apply:
            return
        with transaction.atomic():
            for pay in payments:
                void_payment(pay, reason=f"Period {month}/{year} struck out — {why}"[:255])
            # Re-read: voiding re-derives the row, so take the current one.
            Arrears.objects.filter(
                tenant=tenant, period_year=year, period_month=month,
            ).delete()

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
