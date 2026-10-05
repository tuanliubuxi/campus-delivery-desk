import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("settlements", "0004_alter_financialadjustment_options_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WageCalculationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operation_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("period_start", models.DateField(db_index=True)),
                ("period_end", models.DateField(db_index=True)),
                ("mode", models.CharField(max_length=12)),
                ("result_snapshot", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="wage_calculation_runs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-period_end", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="wagecalculationrun",
            constraint=models.UniqueConstraint(fields=("period_start", "period_end", "mode"), name="settlements_unique_saved_wage_period_mode"),
        ),
    ]
