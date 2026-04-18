"""Initial migration for expenses app."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ExpenseCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "expenses_category",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Expense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(help_text="Date the expense was incurred.")),
                ("category", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="expenses",
                    to="expenses.expensecategory",
                )),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("description", models.CharField(max_length=500)),
                ("reference", models.CharField(
                    blank=True,
                    help_text="Receipt number, invoice ref, etc.",
                    max_length=100,
                )),
                ("period_month", models.PositiveSmallIntegerField(help_text="Month the expense applies to (1-12).")),
                ("period_year", models.PositiveIntegerField(help_text="Year the expense applies to.")),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "expenses_expense",
                "ordering": ["-date", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["period_year", "period_month"], name="expenses_ex_period__idx"),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["category"], name="expenses_ex_categor_idx"),
        ),
    ]
