"""
Bring the ledger into line with the 21 Aug 2026 rent statements.

Four statements were reconciled line by line against production — Road Block /
Khaoya / Donholm / Mt View, Matasia residential and Matasia commercial. Cash
capture was sound in 63 of 64 Eldoret+Nairobi rows; what this command repairs
is everything else the diff turned up.

What it does, in order (order matters — rents are corrected before arrears are
re-derived, and payments are re-pointed before billing is backfilled):

  1. RENTS        monthly_rent set to the statement figure. RB406 was 0.00 and
                  had cleared a zero bill; the six Matasia residential units
                  bill "Rent + Service Charge" on the sheet, so the service
                  charge is folded into rent (the landlord's decision).

  2. REPOINT      Five August payments landed on tenant records that were
                  retired on 15-17 Aug during the roster correction. The bank
                  narration proves the payer and the unit; only the tenant row
                  is wrong. Each is voided (mirror-image reversal) and
                  re-recorded against the correct tenant, so the GL nets to
                  zero and the audit trail states what happened.

  3. MERGE        MCG05 and MCG06 both carry a "Sidai Lonestar Healthcare"
                  record. The statement knows only MCG05. The August payment is
                  moved there and the duplicate is retired.

  4. MISSING      Three payments the statements show as received had no record
                  in any month. Recorded against the statement date.

  5. SPLIT        Two commercial tenants paid an exact 3x multiple in one
                  transfer. Re-recorded as three monthly rows so the rent roll
                  shows one month's rent per row instead of a phantom credit.

  6. NAMES        Spelling drift between statement and system.

DRY-RUN BY DEFAULT. Nothing is written without --apply.

Re-running is safe: every step checks the current state first and skips work
already done.

Usage:
    python manage.py reconcile_aug_2026            # preview
    python manage.py reconcile_aug_2026 --apply    # write

Afterwards, still to run (both dry-run by default):
    python manage.py relabel_rb_ground_floor --apply   # RB01..RB09 -> RB001..RB009
    python manage.py backfill_arrears --apply          # bill the unbilled months
"""
import datetime as _dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

STATEMENT_DATE = _dt.date(2026, 8, 21)

# ---------------------------------------------------------------------------
# 0. Unit labels the statement spells differently — (current, statement, why)
#
# The old label is kept as a UnitAlias so any payment still quoting it keeps
# auto-matching. The RB ground floor (RB01..RB09 -> RB001..RB009) is a bigger
# job with its own command; run relabel_rb_ground_floor for that.
# ---------------------------------------------------------------------------
RELABEL_UNITS = [
    ("MV01", "MVN01", "Mt View is MVN01 on the statement"),
]

# ---------------------------------------------------------------------------
# 1. Rents — (unit label, tenant id, new monthly_rent, why)
# ---------------------------------------------------------------------------
RENTS = [
    ("RB406", 122, Decimal("9000.00"), "was 0.00 — cleared a zero bill while 9,000 was paid"),
    ("MR202", 143, Decimal("20000.00"), "rent 18,000 + service charge 2,000"),
    ("MR301", 144, Decimal("26000.00"), "rent 25,000 + service charge 1,000"),
    ("MR302", 145, Decimal("20000.00"), "rent 18,000 + service charge 2,000"),
    ("MR304", 146, Decimal("12000.00"), "rent 10,000 + service charge 2,000"),
    ("MR306", 168, Decimal("22000.00"), "rent 20,000 + service charge 2,000"),
    ("MR307", 147, Decimal("22000.00"), "rent 20,000 + service charge 2,000"),
]

# ---------------------------------------------------------------------------
# 2/3. Re-point payments — (payment reference, from tenant id, to tenant id, note)
#
# The bank narration for each of these names the payer and the unit; the money
# is on the right unit and the wrong tenant row.
# ---------------------------------------------------------------------------
REPOINT = [
    ("CB0071911_06082026_2", 95, "RB201", 173, "RB201", "narration 'BERYL ALINGA / 90290#RB201'"),
    ("CB1165800_07082026_2", 96, "RB202", 172, "RB202", "narration 'HARON NDIRITU / 90290#RB202'"),
    ("CB0803958_06082026_2", 97, "RB203", 176, "RB203", "narration 'Mariane Mukabwa / 90290#RB203'"),
    ("CB0158001_06082026_2", 107, "RB302", 171, "RB302", "narration 'KEVIN INGANGA / 90290#RB302'"),
    ("CB1188960_10082026_2", 109, "RB304", 170, "RB304", "narration 'JOSEPH WALUKANA / 90290#RP C304'"),
    ("CB0327111_14082026_1", 161, "MCG06", 148, "MCG05", "duplicate Sidai record — statement knows only MCG05"),
]

# Tenant records retired as duplicates once their payments have been moved off.
RETIRE = [
    (161, "MCG06", "duplicate of the MCG05 Sidai Lonestar Healthcare record"),
]

# ---------------------------------------------------------------------------
# 4. Payments on the statement with no record in the system, in any month.
#    (tenant id, unit, amount, source, note)
# ---------------------------------------------------------------------------
MISSING = [
    (141, "MVN01", Decimal("110000.00"), "bank", "Mt View — never captured by the Co-op feed"),
    (166, "MCF12", Decimal("58760.00"), "bank", "Sidai Healthcare Residential"),
    (150, "MCG02", Decimal("22500.00"), "mpesa", "Glow by Ellie Salon"),
]

# ---------------------------------------------------------------------------
# 5. One transfer covering three months — (reference, tenant id, unit, per-month)
# ---------------------------------------------------------------------------
SPLITS = [
    ("S48023247_10082026_2", 175, "MCF01", Decimal("25000.00")),
    ("CB0115181_25082026_1", 177, "MCG07", Decimal("60000.00")),
]
SPLIT_PERIODS = [(2026, 8), (2026, 9), (2026, 10)]

# ---------------------------------------------------------------------------
# 6. Names — (tenant id, first_name, last_name)
# ---------------------------------------------------------------------------
NAMES = [
    (176, "RB203", "Mariane", "Mukabwa"),
    (170, "RB304", "Joseph Simiyu", "Walukanah"),
    (164, "MCG10", "The Shamiri Place", "Limited"),
    (166, "MCF12", "Sidai Healthcare", "Residential"),
]


class Command(BaseCommand):
    help = (
        "Reconcile the ledger against the 21 Aug 2026 rent statements: correct "
        "rents, re-point misrouted payments, merge a duplicate tenant, record "
        "missing payments and split quarterly prepayments. Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the changes. Without this the command only previews them.",
        )

    # -- helpers ------------------------------------------------------------

    def _head(self, text):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{text}"))

    def _do(self, text):
        self.stdout.write(f"  {text}")
        self.changes += 1

    def _skip(self, text):
        self.stdout.write(self.style.WARNING(f"  skip  {text}"))

    def _mismatch(self, text):
        """A tenant id resolved to a different unit than the statement expects.

        Primary keys are not portable between databases — the same id points at
        a different person in dev than in production. Every row in the tables
        above therefore carries the unit label it belongs to, and nothing is
        written unless the id and the label agree. A mismatch means the command
        is pointed at the wrong database (or the roster moved under it), so it
        is reported loudly rather than skipped quietly.
        """
        self.stdout.write(self.style.ERROR(f"  MISMATCH  {text}"))
        self.mismatches += 1

    def _problem(self, prefix, problem):
        """A missing tenant is routine; a tenant on the wrong unit is not."""
        if "not found" in problem:
            self._skip(f"{prefix}: {problem}")
        else:
            self._mismatch(f"{prefix}: {problem}")

    # -- main ---------------------------------------------------------------

    def handle(self, *args, **opts):
        from apps.payments.models import Payment
        from apps.tenants.models import Tenant, TenantStatus

        self.apply = opts["apply"]
        self.changes = 0
        self.mismatches = 0

        def tenant_or_none(tid):
            return Tenant.objects.filter(pk=tid).select_related("unit").first()

        def unit_answers_to(unit, label):
            """True if `label` is the unit's current label or a retired alias.

            Step 0 relabels a unit (MV01 -> MVN01) before the tenant steps run,
            so a table entry keyed on either spelling has to resolve. Aliases
            are exactly the record of "this unit used to be called that".
            """
            if unit is None:
                return False
            wanted = label.upper()
            if unit.label.upper() == wanted:
                return True
            return unit.aliases.filter(label__iexact=wanted).exists()

        def tenant_at(tid, expected_label):
            """Resolve a tenant id, but only if it sits on the expected unit."""
            t = tenant_or_none(tid)
            if t is None:
                return None, f"tenant #{tid} not found"
            if not unit_answers_to(t.unit, expected_label):
                actual = t.unit.label if t.unit else "(no unit)"
                return None, (
                    f"tenant #{tid} is '{t.full_name}' on {actual}, but the "
                    f"statement expects {expected_label} — refusing to touch it"
                )
            return t, None

        # ---- pre-flight -----------------------------------------------------
        # Resolve every tenant id against the unit the statement puts it on
        # BEFORE writing anything. Ids are not portable between databases, so a
        # single mismatch means this is pointed somewhere it should not be —
        # abort with nothing written rather than corrupting half the roster.
        expected = (
            [(tid, label) for label, tid, _r, _w in RENTS]
            + [(tid, lab) for _r, tid, lab, _t, _tl, _w in REPOINT]
            + [(tid, lab) for _r, _f, _fl, tid, lab, _w in REPOINT]
            + [(tid, label) for tid, label, _w in RETIRE]
            + [(tid, label) for tid, label, _a, _s, _w in MISSING]
            + [(tid, label) for _r, tid, label, _p in SPLITS]
            + [(tid, label) for tid, label, _f, _l in NAMES]
        )
        renamed = {old.upper(): new.upper() for old, new, _w in RELABEL_UNITS}
        wrong = []
        for tid, label in expected:
            t = tenant_or_none(tid)
            if t is None:
                continue  # a genuinely absent record is reported per-step
            actual = t.unit.label if t.unit else "(no unit)"
            # Step 0 has not run yet, so accept the pre-relabel spelling too.
            if not unit_answers_to(t.unit, label) and renamed.get(actual.upper()) != label.upper():
                wrong.append(f"#{tid} is '{t.full_name}' on {actual}, statement says {label}")
        if wrong:
            raise CommandError(
                "Pre-flight failed — tenant ids do not match the units the "
                "statement puts them on:\n  "
                + "\n  ".join(wrong)
                + "\n\nPrimary keys are not portable between databases; this "
                "usually means the command is pointed at the wrong one. "
                "Nothing was written."
            )

        # ---- 0. Unit labels -------------------------------------------------
        self._head("0. Unit label -> statement")
        for current, wanted, why in RELABEL_UNITS:
            self._relabel_unit(current, wanted, why)

        # ---- 1. Rents ------------------------------------------------------
        self._head("1. Monthly rent -> statement figure")
        for label, tid, new_rent, why in RENTS:
            t, problem = tenant_at(tid, label)
            if problem:
                self._problem(label, problem)
                continue
            if t.monthly_rent == new_rent:
                self._skip(f"{label} {t.full_name}: already {new_rent}")
                continue
            self._do(f"{label} {t.full_name}: {t.monthly_rent} -> {new_rent}  ({why})")
            if self.apply:
                t.monthly_rent = new_rent
                t.save(update_fields=["monthly_rent", "updated_at"])

        # ---- 2/3. Re-point --------------------------------------------------
        self._head("2. Re-point payments sitting on the wrong tenant record")
        for ref, from_tid, from_label, to_tid, to_label, why in REPOINT:
            src, src_problem = tenant_at(from_tid, from_label)
            dst, dst_problem = tenant_at(to_tid, to_label)
            if src_problem or dst_problem:
                self._problem(ref, src_problem or dst_problem)
                continue
            rows = list(
                Payment.objects.filter(
                    tenant_id=from_tid, reference=ref, voided_at__isnull=True
                ).order_by("pk")
            )
            if not rows:
                self._skip(f"{ref}: nothing left on {src.full_name} (already moved?)")
                continue
            for pay in rows:
                period = self._clamp_period(pay, dst)
                self._do(
                    f"{ref} {pay.amount} {pay.period_month}/{pay.period_year} -> "
                    f"{period[1]}/{period[0]}: {src.full_name} (#{from_tid}) -> "
                    f"{dst.full_name} (#{to_tid})  [{why}]"
                )
                if self.apply:
                    self._move(pay, dst, period, why)

        # ---- retire duplicates ---------------------------------------------
        self._head("3. Retire duplicate tenant records")
        for tid, label, why in RETIRE:
            t, problem = tenant_at(tid, label)
            if problem:
                self._problem(label, problem)
                continue
            if t.status == TenantStatus.ARCHIVED:
                self._skip(f"{label} {t.full_name} (#{tid}): already archived")
                continue
            live = Payment.objects.filter(tenant_id=tid, voided_at__isnull=True).count()
            if live:
                self._skip(f"{label} #{tid}: still has {live} live payment(s) — not retiring")
                continue
            self._do(f"{label} {t.full_name} (#{tid}) -> archived  ({why})")
            if self.apply:
                t.status = TenantStatus.ARCHIVED
                t.move_out_date = t.move_out_date or STATEMENT_DATE
                t.notes = (t.notes + f"\nArchived by reconcile_aug_2026: {why}").strip()
                t.save(update_fields=["status", "move_out_date", "notes", "updated_at"])

        # ---- 4. Missing payments -------------------------------------------
        self._head("4. Payments on the statement with no record in the system")
        for tid, label, amount, source, why in MISSING:
            t, problem = tenant_at(tid, label)
            if problem:
                self._problem(label, problem)
                continue
            key = f"STMT-2026-08-{label}"
            if Payment.objects.filter(tenant_id=tid, idempotency_key=key).exists():
                self._skip(f"{label} {t.full_name}: already recorded")
                continue
            self._do(f"{label} {t.full_name}: record {amount} ({source}, 8/2026)  [{why}]")
            if self.apply:
                self._record(
                    tenant=t, amount=amount, period=(2026, 8), source=source,
                    reference=key, idempotency_key=key,
                    notes=f"Recorded from the 21 Aug 2026 rent statement — {why}.",
                )

        # ---- 5. Quarterly prepayments --------------------------------------
        self._head("5. One transfer covering three months -> one row per month")
        for ref, tid, label, per_month in SPLITS:
            t = tenant_or_none(tid)
            if t is None:
                self._skip(f"{label}: tenant #{tid} not found")
                continue
            lump = (
                Payment.objects.filter(tenant_id=tid, reference=ref, voided_at__isnull=True)
                .order_by("pk").first()
            )
            if lump is None:
                self._skip(f"{ref}: no live lump payment on {t.full_name} (already split?)")
                continue
            if lump.amount != per_month * len(SPLIT_PERIODS):
                self._skip(
                    f"{ref}: {lump.amount} is not {len(SPLIT_PERIODS)} x {per_month} — leaving alone"
                )
                continue
            months = ", ".join(f"{m}/{y}" for y, m in SPLIT_PERIODS)
            self._do(f"{label} {t.full_name}: {lump.amount} -> {len(SPLIT_PERIODS)} x {per_month} ({months})")
            if self.apply:
                self._split(lump, t, per_month, ref)

        # ---- 6. Names -------------------------------------------------------
        self._head("6. Name spelling -> statement")
        for tid, label, first, last in NAMES:
            t, problem = tenant_at(tid, label)
            if problem:
                self._problem(label, problem)
                continue
            if (t.first_name, t.last_name) == (first, last):
                self._skip(f"{label}: already '{first} {last}'")
                continue
            self._do(f"{label}: '{t.full_name}' -> '{first} {last}'")
            if self.apply:
                t.first_name, t.last_name = first, last
                t.save(update_fields=["first_name", "last_name", "updated_at"])

        # ---- 7. Zero-rent arrears rows that swallowed real cash -------------
        # Deliberately last: step 2 moves money off the duplicate records first,
        # so a row only reaches here if the cash genuinely belongs to it.
        self._head("7. Arrears rows billed at zero that nonetheless took money")
        self._repair_zero_bills()

        # ---- summary --------------------------------------------------------
        if not self.apply:
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN — {self.changes} change(s) would be written. "
                f"Re-run with --apply."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nApplied {self.changes} change(s). Now run:\n"
                f"  python manage.py relabel_rb_ground_floor --apply\n"
                f"  python manage.py backfill_arrears --apply"
            ))

    # -- write helpers ------------------------------------------------------

    @staticmethod
    def _clamp_period(payment, dst_tenant):
        """Never book a payment into a month before the tenant moved in.

        FIFO had allocated some of these against the retired tenant's older
        arrears. The replacement tenant has no such history, so anything earlier
        than their move-in month moves forward to it.
        """
        move_in = dst_tenant.move_in_date
        year, month = payment.period_year, payment.period_month
        if move_in and (year, month) < (move_in.year, move_in.month):
            return (move_in.year, move_in.month)
        return (year, month)

    def _repair_zero_bills(self):
        """Re-derive arrears rows raised at zero rent that then took real money.

        ``_update_arrears`` never rewrites an existing obligation — and rightly
        so, since an opening-balance row carries a brought-forward figure rather
        than a month's rent, and recomputing it from ``monthly_rent`` is exactly
        what corrupted the cutover balances before. ``backfill_arrears`` uses
        ``get_or_create`` and skips any period that already has a row. So a row
        raised while the tenant's rent was still 0.00 stays at zero forever, and
        every shilling paid against it reads as credit: RB406 shows roughly
        18,000 in hand while owing two months.

        The repair is scoped to rows where cash actually landed on a zero
        obligation. That combination cannot be legitimate — a genuinely
        rent-free period attracts no payment — whereas a zero row with no
        payment may well be a clean cutover, and inventing a month's rent for it
        would repeat the original corruption. Those are left alone.
        """
        from apps.payments.models import Arrears
        from apps.payments.services import _update_arrears, expected_vat_for

        stranded = (
            Arrears.objects.filter(expected_rent=0, amount_paid__gt=0, tenant__monthly_rent__gt=0)
            .select_related("tenant", "tenant__unit")
            .order_by("tenant__unit__label", "period_year", "period_month")
        )
        if not stranded:
            self._skip("none — no zero-rent row is holding cash")
            return

        for arr in stranded:
            tenant = arr.tenant
            rent = tenant.monthly_rent
            vat = expected_vat_for(tenant, rent)
            label = tenant.unit.label if tenant.unit else "(no unit)"
            self._do(
                f"{label} {tenant.full_name} {arr.period_month}/{arr.period_year}: "
                f"billed 0.00 but holds {arr.amount_paid} -> obligation {rent}"
                + (f" + VAT {vat}" if vat else "")
            )
            if not self.apply:
                continue
            with transaction.atomic():
                # Set the obligation, then let the canonical routine re-derive
                # amount_paid, balance and is_cleared from it.
                Arrears.objects.filter(pk=arr.pk).update(expected_rent=rent, expected_vat=vat)
                _update_arrears(tenant, arr.period_month, arr.period_year)

    def _relabel_unit(self, current, wanted, why):
        """Rename a unit, keeping the old label as a payment-matching alias."""
        from apps.buildings.models import Unit, UnitAlias

        if Unit.objects.filter(label__iexact=wanted).exists():
            self._skip(f"{current} -> {wanted}: already {wanted}")
            return
        unit = Unit.objects.filter(label__iexact=current).first()
        if unit is None:
            self._skip(f"{current} -> {wanted}: no unit labelled {current}")
            return
        self._do(f"{current} -> {wanted}  (alias kept: {current}; {why})")
        if not self.apply:
            return
        with transaction.atomic():
            if unit.statement_descriptor:
                unit.statement_descriptor = unit.statement_descriptor.replace(current, wanted)
            unit.label = wanted
            unit.full_clean()
            unit.save(update_fields=["label", "statement_descriptor", "updated_at"])
            alias, created = UnitAlias.objects.get_or_create(
                unit=unit, label=current,
                defaults={"note": "Retired label (reconcile_aug_2026)"},
            )
            if created:
                alias.full_clean()

    def _record(self, *, tenant, amount, period, source, reference, idempotency_key, notes):
        from apps.payments.services import process_payment

        year, month = period
        return process_payment(
            tenant=tenant, amount=amount, payment_date=STATEMENT_DATE,
            period_month=month, period_year=year, source=source,
            reference=reference, idempotency_key=idempotency_key, notes=notes,
        )

    def _move(self, payment, dst_tenant, period, why):
        """Void on the wrong tenant, re-record on the right one."""
        from apps.payments.services import process_payment, void_payment

        original_date = payment.payment_date
        amount, source, ref = payment.amount, payment.source, payment.reference
        key = payment.idempotency_key or ref

        with transaction.atomic():
            void_payment(
                payment,
                reason=f"Re-pointed to {dst_tenant.full_name} (#{dst_tenant.pk}) — {why}"[:255],
            )
            year, month = period
            process_payment(
                tenant=dst_tenant, amount=amount, payment_date=original_date,
                period_month=month, period_year=year, source=source,
                reference=ref, idempotency_key=key,
                notes=(
                    f"Re-pointed from tenant #{payment.tenant_id} by "
                    f"reconcile_aug_2026 — {why}."
                ),
            )

    def _split(self, lump, tenant, per_month, ref):
        """Void the single lump and re-record it as one row per month."""
        from apps.payments.services import process_payment, void_payment

        pay_date, source = lump.payment_date, lump.source

        with transaction.atomic():
            void_payment(
                lump,
                reason=f"Split into {len(SPLIT_PERIODS)} monthly rows of {per_month}"[:255],
            )
            for year, month in SPLIT_PERIODS:
                process_payment(
                    tenant=tenant, amount=per_month, payment_date=pay_date,
                    period_month=month, period_year=year, source=source,
                    reference=ref, idempotency_key=f"{ref}#{year}-{month:02d}",
                    notes=(
                        f"One month of a {per_month * len(SPLIT_PERIODS)} quarterly "
                        f"transfer, split by reconcile_aug_2026."
                    ),
                )
