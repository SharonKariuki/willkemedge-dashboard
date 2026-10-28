from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0023_coopipnevent_void_requeue_count'),
    ]

    operations = [
        migrations.AlterField(
            model_name='utilitycharge',
            name='charge_type',
            field=models.CharField(choices=[('electricity', 'Electricity'), ('garbage', 'Garbage collection'), ('security', 'Security'), ('service_charge', 'Service charge'), ('utility', 'Water or other utility'), ('late_fee', 'Late payment penalty'), ('parking', 'Parking'), ('damage', 'Damage or repair recharge')], default='utility', help_text='What the charge is for; decides the income or expense account.', max_length=20),
        ),
    ]
