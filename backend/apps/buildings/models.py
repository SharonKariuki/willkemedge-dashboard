"""
Building and Unit models — updated with UNDER_MAINTENANCE status and
MaintenanceRequest model for tracking repairs per unit.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Upper


class UnitStatus(models.TextChoices):
    VACANT = "vacant", "Vacant"
    OCCUPIED_PAID = "occupied_paid", "Occupied — Paid"
    OCCUPIED_PARTIAL = "occupied_partial", "Occupied — Partial"
    OCCUPIED_UNPAID = "occupied_unpaid", "Occupied — Unpaid"
    ARREARS = "arrears", "Arrears"
    UNDER_MAINTENANCE = "under_maintenance", "Under Maintenance"


# Statuses that count as a unit being occupied by a tenant. Deliberately
# excludes VACANT *and* UNDER_MAINTENANCE — a unit under renovation has no
# tenant and earns no rent, so counting it as occupied overstates occupancy.
OCCUPIED_UNIT_STATUSES = (
    UnitStatus.OCCUPIED_PAID,
    UnitStatus.OCCUPIED_PARTIAL,
    UnitStatus.OCCUPIED_UNPAID,
    UnitStatus.ARREARS,
)


class PropertyType(models.TextChoices):
    """What kind of property this is — drives how income/expenses are handled.

    RENTAL      : normal rental buildings (rent via tenants + payments).
    FARM        : farms (FSE/FMM/FNN) — manual income + expenses, no tenants.
    EXPENSE_ONLY: e.g. Baobab Karen (KRN) family home — expenses only, income
                  entry is disabled.
    """

    RENTAL = "rental", "Rental Property"
    FARM = "farm", "Farm (manual income + expenses)"
    EXPENSE_ONLY = "expense_only", "Expenses Only (no income)"


class UnitClassification(models.TextChoices):
    RESIDENTIAL = "RESIDENTIAL", "Residential"
    BUSINESS = "BUSINESS", "Business / Commercial"


class Building(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(
        max_length=10, unique=True, null=True, blank=True,
        help_text=(
            "Short property code used as the prefix for this building's unit "
            "labels, e.g. 'DON', 'RB', 'MC'. Must be unique across all properties."
        ),
    )
    address = models.TextField(blank=True)
    total_floors = models.PositiveSmallIntegerField(default=1)
    property_type = models.CharField(
        max_length=16,
        choices=PropertyType.choices,
        default=PropertyType.RENTAL,
        help_text="Rental (tenant rent), Farm (manual income + expenses), or Expenses-only (e.g. Baobab Karen).",
    )
    notes = models.TextField(blank=True)

    @property
    def allows_income(self) -> bool:
        """Expense-only properties (e.g. Baobab Karen) cannot record income."""
        return self.property_type != PropertyType.EXPENSE_ONLY

    # --- Statement / receipt header & payment options -----------------------
    # These appear verbatim on the rent statement PDF a tenant receives after
    # paying. Leave blank to fall back to project-wide defaults.
    legal_name = models.CharField(
        max_length=160, blank=True,
        help_text="Legal entity name shown on statements, e.g. 'Wilkem Ventures Company Ltd.'",
    )
    postal_address = models.CharField(
        max_length=160, blank=True,
        help_text="Postal address line, e.g. 'PO Box 66741 - 00800, Nairobi, Kenya'.",
    )
    contact_phone = models.CharField(max_length=80, blank=True)
    contact_email = models.EmailField(blank=True)

    water_rate_per_unit = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("200.00"),
        help_text="Tariff charged per unit of water consumed (KES). Donholm bills at 200/unit.",
    )

    paybill_number = models.CharField(
        max_length=20, blank=True,
        help_text="M-Pesa Paybill business number, e.g. '400222'.",
    )
    paybill_account_format = models.CharField(
        max_length=60, blank=True,
        help_text=(
            "Paybill account number. Use '{unit}' as a placeholder for the unit "
            "label, e.g. '90290#{unit}' or a fixed value like '839800'."
        ),
    )
    bank_name = models.CharField(max_length=80, blank=True)
    bank_branch = models.CharField(max_length=80, blank=True)
    bank_account = models.CharField(max_length=40, blank=True)
    bank_account_name = models.CharField(max_length=120, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buildings_building"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def paybill_account_for(self, unit_label: str) -> str:
        """Resolve the Paybill account string for a given unit label."""
        fmt = self.paybill_account_format or ""
        if "{unit}" in fmt:
            return fmt.replace("{unit}", unit_label or "")
        return fmt

    def clean(self):
        super().clean()
        fmt = (self.paybill_account_format or "").strip()
        # Allow blank, a literal value, or a format string that uses {unit}.
        # Reject typo placeholders (`{building}`, `{tenant}`, …) before they
        # silently produce empty paybill accounts on rent statements.
        if "{" in fmt or "}" in fmt:
            if "{unit}" not in fmt:
                raise ValidationError({
                    "paybill_account_format": (
                        "Paybill account format may only use the '{unit}' placeholder, "
                        "or be a fixed literal value with no braces."
                    ),
                })


class Unit(models.Model):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="units")
    label = models.CharField(max_length=30, help_text="Unit identifier, e.g. 'A1', 'B12', 'Shop 3'.")
    floor = models.PositiveSmallIntegerField(default=0)
    unit_type = models.CharField(
        max_length=30,
        choices=[
            ("single", "Single Room"),
            ("double", "Double Room"),
            ("bedsitter", "Bedsitter"),
            ("1br", "1 Bedroom"),
            ("2br", "2 Bedroom"),
            ("3br", "3 Bedroom"),
            ("shop", "Shop / Commercial"),
        ],
        default="single",
    )
    classification = models.CharField(
        max_length=15,
        choices=UnitClassification.choices,
        default=UnitClassification.RESIDENTIAL,
        db_index=True,
    )
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=UnitStatus.choices, default=UnitStatus.VACANT, db_index=True
    )
    statement_descriptor = models.CharField(
        max_length=80, blank=True,
        help_text=(
            "Right-hand cell on the rent statement, e.g. 'Unit G05 - Hospital' "
            "or 'House 3A - Donholm Estate'. Leave blank to auto-build from "
            "the unit label and building name."
        ),
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buildings_unit"
        ordering = ["building__name", "floor", "label"]
        constraints = [
            models.UniqueConstraint(fields=["building", "label"], name="unique_unit_per_building"),
            # Labels must be unique across ALL buildings (case-insensitive) so a
            # payment reference like '90290#DON1A' maps to exactly one unit on any
            # channel — no ambiguity for the matcher to guess at.
            models.UniqueConstraint(Upper("label"), name="unique_unit_label_global"),
        ]

    def __str__(self) -> str:
        return f"{self.building.name} — {self.label}"

    def save(self, *args, **kwargs):
        self.label = (self.label or "").strip()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.label = (self.label or "").strip()
        if not self.label:
            return
        clash = Unit.objects.filter(label__iexact=self.label).exclude(pk=self.pk)
        if clash.exists():
            other = clash.select_related("building").first()
            suggestion = f"{self.building.code}{self.label}" if (self.building_id and self.building.code) else self.label
            raise ValidationError({
                "label": (
                    f"Label '{self.label}' is already used in '{other.building.name}'. "
                    f"Unit labels must be unique across ALL buildings so M-Pesa and "
                    f"bank payments can be matched automatically. Use the building's "
                    f"code as a prefix, e.g. '{suggestion}'."
                )
            })


class UnitAlias(models.Model):
    """A retired/legacy unit label, kept so payments that still use the OLD
    account reference (e.g. '90290#G01' before the building-code relabel) keep
    auto-matching during the transition.

    The matcher tries current `Unit.label` first, then falls back to these.
    Aliases are globally unique and must not clash with any current unit label,
    so the fallback is never ambiguous. Retire (delete) them once tenants are on
    the new codes and statements have been reissued.
    """
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="aliases")
    label = models.CharField(max_length=30, help_text="Old unit label, e.g. 'G01'.")
    note = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "buildings_unit_alias"
        verbose_name_plural = "unit aliases"
        constraints = [
            models.UniqueConstraint(Upper("label"), name="unique_unit_alias_label_global"),
        ]

    def __str__(self) -> str:
        return f"{self.label} → {self.unit}"

    def save(self, *args, **kwargs):
        self.label = (self.label or "").strip()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.label = (self.label or "").strip()
        if not self.label:
            return
        # An alias must never collide with a CURRENT unit label, or the matcher's
        # fallback would be ambiguous (which unit does '90290#G01' mean?).
        if Unit.objects.filter(label__iexact=self.label).exists():
            raise ValidationError({
                "label": f"Alias '{self.label}' clashes with a current unit label; "
                         f"aliases may only point to retired labels.",
            })


class MaintenanceStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    DONE = "done", "Done"


class MaintenanceRequest(models.Model):
    """Tracks repair/maintenance work for a specific unit.
    Cost is automatically synced to expenses when created."""

    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="maintenance_requests")
    description = models.TextField(help_text="What needs to be repaired / done.")
    cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Estimated or actual cost in KES."
    )
    status = models.CharField(max_length=15, choices=MaintenanceStatus.choices, default=MaintenanceStatus.OPEN)
    reported_date = models.DateField()
    completed_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    # Reference to the auto-created expense (if cost > 0)
    expense = models.OneToOneField(
        "expenses.Expense",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="maintenance_request",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buildings_maintenance"
        ordering = ["-reported_date"]

    def __str__(self) -> str:
        return f"{self.unit} — {self.description[:60]} ({self.status})"
