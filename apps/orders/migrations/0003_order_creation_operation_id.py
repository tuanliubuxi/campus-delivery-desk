"""Backfill stable, unique idempotency keys for existing and future orders."""

import uuid

from django.db import migrations, models


def populate_creation_operation_ids(apps, schema_editor):
    order_model = apps.get_model("orders", "Order")
    for order in order_model.objects.filter(creation_operation_id__isnull=True).iterator():
        order.creation_operation_id = uuid.uuid4()
        order.save(update_fields=["creation_operation_id"])


class Migration(migrations.Migration):
    dependencies = [("orders", "0002_order_entry_note")]

    operations = [
        migrations.AddField(
            model_name="order",
            name="creation_operation_id",
            field=models.UUIDField(null=True, unique=True),
        ),
        migrations.RunPython(populate_creation_operation_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="order",
            name="creation_operation_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
