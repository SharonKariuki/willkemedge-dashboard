"""
Building and Unit models.

A Building groups Units. Each Unit has a status reflecting its current
occupancy and payment state. Status transitions are handled by the
service layer (services.py), not by direct field assignment.

Unit.classification ("RESIDENTIAL" / "BUSINESS") is the tax-domain trigger
consumed by the payment system. It is intentionally separate from
unit_type (the physical layout descriptor).
"""
from django.db import models


class UnitStatus(models.TextChoices):
    """
    Unit lifecycle states:
    - VACANT: no active tenant, available for move-in
    - OCCUPIED_PAID: tenant present, current month fully paid
    - OCCUPIED_PARTIAL: tenant present, partial payment received
    - OCCUPIED_UNPAID: tenant present, no payment this month
    - ARREARS: tenant present, past-due balance outstanding
    """

    VACANT = "vacant", "Vacant"
    OCCUPIED_PAID = "occupied_paid", "Occupied — Paid"
    OCCUPIED_PARTIAL = "occupied_partial", "Occupied — Partial"
    OCCUPIED_UNPAID = "occupied_unpaid", "Occupied — Unpaid"
    ARREARS = "arrears", "Arrears"


class UnitClassification(models.TextChoices):
    """
    Tax-domain classification that drives VAT logic in the payment system.

    RESIDENTIAL → 0 % VAT (exempt)
    BUSINESS    → 16 % VAT applied to base rent
    """

    RESIDENTIAL = "RESIDENTIAL", "Residential"
    BUSINESS = "BUSINESS", "Business / Commercial"


class Building(models.Model):
    """A physical building containing rental units."""

    name = models.CharField(max_length=120, unique=True)
    address = models.TextField(blank=True)
    total_floors = models.PositiveSmallIntegerField(default=1)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buildings_building"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Unit(models.Model):
    """A rentable unit within a building."""

    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name="units",
    )
    label = models.CharField(
        max_length=30,
        help_text="Unit identifier, e.g. 'A1', 'B12', 'Shop 3'.",
    )
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
    # Tax-domain trigger: drives VAT in payment processing.
    # Kept separate from unit_type because physical layout and tax treatment
    # are independent concerns (e.g. a bedsitter can be leased commercially).
    classification = models.CharField(
        max_length=15,
        choices=UnitClassification.choices,
        default=UnitClassification.RESIDENTIAL,
        db_index=True,
        help_text=(
            "RESIDENTIAL = 0 % VAT. "
            "BUSINESS = 16 % VAT applied to base rent at payment time."
        ),
    )
    monthly_rent = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Monthly rent in KES.",
    )
    status = models.CharField(
        max_length=20,
        choices=UnitStatus.choices,
        default=UnitStatus.VACANT,
        db_index=True,
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buildings_unit"
        ordering = ["building__name", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["building", "label"],
                name="unique_unit_per_building",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.building.name} — {self.label}"
