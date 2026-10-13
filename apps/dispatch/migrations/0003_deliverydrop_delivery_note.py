from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("dispatch", "0002_routebatch")]

    operations = [
        migrations.AddField(
            model_name="deliverydrop",
            name="delivery_note",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
