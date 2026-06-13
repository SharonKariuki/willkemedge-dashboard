from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0006_alter_account_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='expense',
            name='payment_method',
            field=models.CharField(
                max_length=10,
                choices=[('bank', 'Bank / MPESA'), ('petty_cash', 'Petty Cash')],
                default='bank',
                help_text='How this expense was paid — determines whether 1020 (bank) or 1010 (petty cash) is credited.',
            ),
        ),
    ]
