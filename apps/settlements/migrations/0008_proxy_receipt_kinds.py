from django.db import migrations, models
from django.db.models import Q


def classify_receipts(apps, schema_editor):
    Receipt = apps.get_model("settlements", "ProxyRecipientReceipt")
    Receipt.objects.filter(settlement__isnull=False).update(kind="SETTLEMENT")


class Migration(migrations.Migration):
    dependencies = [("settlements", "0007_upstairs_price_review")]

    operations = [
        migrations.AddField(
            model_name="proxyrecipientreceipt", name="kind",
            field=models.CharField(
                choices=[("DELIVERY", "配送凭证"), ("SETTLEMENT", "结算凭证")],
                default="DELIVERY", max_length=12,
            ),
        ),
        migrations.RunPython(classify_receipts, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="proxyrecipientreceipt", name="settlements_unique_proxy_receipt_version",
        ),
        migrations.RemoveConstraint(
            model_name="proxyrecipientreceipt", name="settlements_one_active_proxy_receipt",
        ),
        migrations.AddConstraint(
            model_name="proxyrecipientreceipt",
            constraint=models.UniqueConstraint(
                fields=("proxy_recipient", "kind", "version_no"),
                name="settlements_unique_proxy_receipt_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="proxyrecipientreceipt",
            constraint=models.UniqueConstraint(
                condition=Q(is_active=True), fields=("proxy_recipient", "kind"),
                name="settlements_one_active_proxy_receipt",
            ),
        ),
    ]
