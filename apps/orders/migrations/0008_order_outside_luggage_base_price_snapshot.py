from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("orders", "0007_simple_upstairs_counts_and_suggestion")]

    operations = [
        migrations.AddField(
            model_name="order",
            name="outside_luggage_base_price_snapshot",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
        ),
    ]
