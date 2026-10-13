from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("config_center", "0007_siteconfiguration_image_quality_and_more")]

    operations = [
        migrations.AddField(
            model_name="siteconfiguration",
            name="outside_luggage_base_price",
            field=models.DecimalField(
                decimal_places=2, default=3, max_digits=8,
                validators=[MinValueValidator(Decimal("0"))],
            ),
        ),
    ]
