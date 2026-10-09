from decimal import Decimal

import django.core.validators
from django.db import migrations, models


def fill_unset_default_rate(apps, schema_editor):
    configuration = apps.get_model("config_center", "SiteConfiguration")
    configuration.objects.filter(default_wage_rate__isnull=True).update(
        default_wage_rate=Decimal("1.0000")
    )


class Migration(migrations.Migration):
    dependencies = [("config_center", "0005_replace_commissions_with_default_wage_rate")]

    operations = [
        migrations.AlterField(
            model_name="siteconfiguration",
            name="default_wage_rate",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                default=Decimal("1.0000"),
                help_text="所有配送员默认继承 1.0；个人比例可单独覆盖。",
                max_digits=5,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0")),
                    django.core.validators.MaxValueValidator(Decimal("1")),
                ],
            ),
        ),
        migrations.RunPython(fill_unset_default_rate, migrations.RunPython.noop),
    ]
