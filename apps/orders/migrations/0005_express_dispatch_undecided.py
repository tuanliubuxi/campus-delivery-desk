from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("orders", "0004_order_creation_fingerprint")]

    operations = [
        migrations.AlterField(
            model_name="expressorderdetail",
            name="dispatch_mode",
            field=models.CharField(
                choices=[
                    ("UNDECIDED", "待配送员选择"),
                    ("ROUTE", "路线配送"),
                    ("DIRECT_CUSTOMER", "客户直送"),
                ],
                default="UNDECIDED",
                max_length=20,
            ),
        ),
    ]
