"""Store a deterministic request fingerprint beside each order idempotency key."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("orders", "0003_order_creation_operation_id")]

    operations = [
        migrations.AddField(
            model_name="order",
            name="creation_fingerprint",
            field=models.CharField(blank=True, editable=False, max_length=64),
        ),
    ]
