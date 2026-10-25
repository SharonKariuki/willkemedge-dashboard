"""KYC documents move into the database.

Render has no persistent disk, so every deploy wiped the files uploads wrote to
MEDIA_ROOT. From now on the bytes live in ``TenantDocument.data``.

The copy step below pulls in any file still on disk where ``migrate`` runs.
That rescues local copies; on Render the build runs on a fresh disk, so
production files are already gone. Rows whose file is gone stay as they are,
and the page marks them as needing a fresh upload.
"""
import apps.tenants.models
from django.db import migrations, models

MAGIC = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


def _content_type(head: bytes) -> str:
    for prefix, kind in MAGIC:
        if head.startswith(prefix):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def copy_surviving_files(apps, schema_editor):
    TenantDocument = apps.get_model("tenants", "TenantDocument")
    for doc in TenantDocument.objects.filter(data__isnull=True).exclude(file=""):
        try:
            with doc.file.open("rb") as fh:
                content = fh.read()
        except OSError:
            continue  # wiped by an earlier deploy; nothing to copy
        doc.data = content
        doc.content_type = _content_type(content[:16])
        doc.size = len(content)
        doc.save(update_fields=["data", "content_type", "size"])


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0009_tenant_tenant_monthly_rent_non_negative_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantdocument',
            name='content_type',
            field=models.CharField(blank=True, editable=False, max_length=100),
        ),
        migrations.AddField(
            model_name='tenantdocument',
            name='data',
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tenantdocument',
            name='size',
            field=models.PositiveIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AlterField(
            model_name='tenantdocument',
            name='file',
            field=models.FileField(blank=True, upload_to=apps.tenants.models.tenant_document_path),
        ),
        migrations.RunPython(copy_surviving_files, migrations.RunPython.noop),
    ]
