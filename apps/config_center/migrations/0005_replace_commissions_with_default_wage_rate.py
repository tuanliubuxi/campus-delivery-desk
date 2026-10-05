from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("config_center", "0004_alter_businesstypeconfig_base_price_and_more")]

    operations = [
        migrations.AddField(
            model_name="siteconfiguration",
            name="default_wage_rate",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text="所有配送员默认继承此比例；留空时仅阻止比例工资计算。",
                max_digits=5,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0")),
                    django.core.validators.MaxValueValidator(Decimal("1")),
                ],
            ),
        ),
        migrations.DeleteModel(name="CommissionConfig"),
    ]
