import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('buildings', '0001_initial'),
        ('expenses', '0007_expense_payment_method'),
    ]

    operations = [
        migrations.CreateModel(
            name='JournalEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('period_month', models.PositiveSmallIntegerField(editable=False)),
                ('period_year', models.PositiveIntegerField(editable=False)),
                ('memo', models.CharField(max_length=255)),
                ('reference', models.CharField(blank=True, max_length=100)),
                ('source_type', models.CharField(blank=True, max_length=30)),
                ('source_id', models.PositiveIntegerField(blank=True, null=True)),
                ('kind', models.CharField(
                    choices=[('normal', 'Normal'), ('reversal', 'Reversal')],
                    default='normal',
                    max_length=10,
                )),
                ('is_posted', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('building', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='journal_entries',
                    to='buildings.building',
                )),
            ],
            options={
                'db_table': 'ledger_journal_entry',
                'ordering': ['-date', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='JournalLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('debit', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=14)),
                ('credit', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=14)),
                ('description', models.CharField(blank=True, max_length=255)),
                ('account', models.ForeignKey(
                    limit_choices_to={'is_header': False},
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='journal_lines',
                    to='expenses.account',
                )),
                ('entry', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lines',
                    to='ledger.journalentry',
                )),
            ],
            options={
                'db_table': 'ledger_journal_line',
            },
        ),
        migrations.CreateModel(
            name='Budget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_month', models.PositiveSmallIntegerField()),
                ('period_year', models.PositiveIntegerField()),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14)),
                ('account', models.ForeignKey(
                    limit_choices_to={'is_header': False},
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='budgets',
                    to='expenses.account',
                )),
                ('building', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='budgets',
                    to='buildings.building',
                )),
            ],
            options={
                'db_table': 'ledger_budget',
            },
        ),
        migrations.AddConstraint(
            model_name='journalentry',
            constraint=models.UniqueConstraint(
                fields=['source_type', 'source_id', 'kind'],
                name='unique_journal_entry_per_source_kind',
            ),
        ),
        migrations.AddIndex(
            model_name='journalentry',
            index=models.Index(fields=['period_year', 'period_month'], name='ledger_je_period_idx'),
        ),
        migrations.AddIndex(
            model_name='journalentry',
            index=models.Index(fields=['building', 'period_year', 'period_month'], name='ledger_je_building_period_idx'),
        ),
        migrations.AddIndex(
            model_name='journalentry',
            index=models.Index(fields=['source_type', 'source_id'], name='ledger_je_source_idx'),
        ),
        migrations.AddConstraint(
            model_name='journalline',
            constraint=models.CheckConstraint(
                condition=~(models.Q(debit__gt=0) & models.Q(credit__gt=0)),
                name='ledger_line_not_both_sides',
            ),
        ),
        migrations.AddConstraint(
            model_name='journalline',
            constraint=models.CheckConstraint(
                condition=models.Q(debit__gt=0) | models.Q(credit__gt=0),
                name='ledger_line_nonzero',
            ),
        ),
        migrations.AddConstraint(
            model_name='budget',
            constraint=models.UniqueConstraint(
                fields=['account', 'building', 'period_month', 'period_year'],
                name='unique_budget_per_account_period',
            ),
        ),
    ]
