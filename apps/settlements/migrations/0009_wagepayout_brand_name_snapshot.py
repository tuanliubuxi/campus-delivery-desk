from django.db import migrations, models


def snapshot_existing_brand(apps, schema_editor):
    configuration = apps.get_model("config_center", "SiteConfiguration")
    config = configuration.objects.filter(pk=1).first()
    brand = (config.receipt_brand_name if config else "").strip() or "校驿"
    apps.get_model("settlements", "WagePayout").objects.filter(
        status__in=["READY", "PAID"]
    ).update(brand_name_snapshot=brand)


class Migration(migrations.Migration):
    dependencies = [("settlements", "0008_proxy_receipt_kinds")]

    operations = [
        migrations.AddField(
            model_name="wagepayout",
            name="brand_name_snapshot",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.RunPython(snapshot_existing_brand, migrations.RunPython.noop),
    ]
