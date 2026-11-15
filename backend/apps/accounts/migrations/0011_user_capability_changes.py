from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_roles_auditor_buildings"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="extra_capabilities",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="user",
            name="removed_capabilities",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
