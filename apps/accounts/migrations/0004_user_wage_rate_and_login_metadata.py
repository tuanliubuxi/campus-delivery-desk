from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_alter_user_managers")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="wage_rate_override",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text="仅配送员可设置；留空时继承系统默认计薪比例。",
                max_digits=5,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0")),
                    django.core.validators.MaxValueValidator(Decimal("1")),
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(("role", "COURIER"), ("wage_rate_override__isnull", True), _connector="OR"),
                name="account_non_courier_no_wage_override",
            ),
        ),
        migrations.AddField(model_name="activeloginlease", name="ip_address", field=models.GenericIPAddressField(blank=True, null=True)),
        migrations.AddField(model_name="activeloginlease", name="user_agent", field=models.TextField(blank=True)),
        migrations.AddField(model_name="activeloginlease", name="device_summary", field=models.CharField(blank=True, max_length=160)),
    ]
