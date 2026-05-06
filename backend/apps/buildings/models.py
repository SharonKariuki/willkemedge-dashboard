"""
Building and Unit models — updated with UNDER_MAINTENANCE status and
MaintenanceRequest model for tracking repairs per unit.
"""
from django.db import models


class UnitStatus(models.TextChoices):
    VACANT = "vacant", "Vacant"
    OCCUPIED_PAID = "occupied_paid", "Occupied — Paid"
    OCCUPIED_PARTIAL = "occupied_partial", "Occupied — Partial"
    OCCUPIED_UNPAID = "occupied_unpaid", "Occupied — Unpaid"
    ARREARS = "arrears", "Arrears"
    UNDER_MAINTENANCE = "under_maintenance", "Under Maintenance"


class UnitClassification(models.TextChoices):
    RESIDENTIAL = "RESIDENTIAL", "Residential"
    BUSINESS = "BUSINESS", "Business / Commercial"


class Building(models.Model):
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
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "buildings_unit"
        ordering = ["building__name", "floor", "label"]
        constraints = [
            models.UniqueConstraint(fields=["building", "label"], name="unique_unit_per_building"),
        ]

    def __str__(self) -> str:
        return f"{self.building.name} — {self.label}"


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
