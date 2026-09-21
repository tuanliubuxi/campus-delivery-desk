"""Seed the required V1 business types and singleton configuration rows."""

from django.db import migrations

BUSINESSES = [
    ("EXPRESS", "快递代取", "📦", "2.00", True, "1.00"),
    ("TAKEOUT", "校门口外卖", "🥡", "3.00", True, "2.00"),
    ("KFC", "周四 KFC", "🍗", "10.00", True, "5.00"),
    ("GROCERY", "果蔬零食", "🥬", "5.00", True, "2.00"),
    ("ERRAND", "跑腿送东西", "🏃", "3.00", True, "2.00"),
    ("LUGGAGE_UPSTAIRS", "行李搬上楼", "🧳", None, False, "0.00"),
]


def seed_configuration(apps, schema_editor):
    Building = apps.get_model("config_center", "Building")
    BusinessTypeConfig = apps.get_model("config_center", "BusinessTypeConfig")
    CommissionConfig = apps.get_model("config_center", "CommissionConfig")
    QuickLocationPhrase = apps.get_model("config_center", "QuickLocationPhrase")
    SiteConfiguration = apps.get_model("config_center", "SiteConfiguration")

    SiteConfiguration.objects.get_or_create(pk=1)
    for number in range(1, 19):
        Building.objects.get_or_create(
            code=str(number),
            defaults={
                "name": f"{number}号楼",
                "zone": "SOUTH" if number <= 10 else "NORTH",
                "route_order": number,
            },
        )
    for order, (business_type, name, icon, base, urgent_supported, urgent_fee) in enumerate(
        BUSINESSES, start=1
    ):
        BusinessTypeConfig.objects.get_or_create(
            business_type=business_type,
            defaults={
                "display_name": name,
                "icon": icon,
                "sort_order": order,
                "base_price": base,
                "urgent_supported": urgent_supported,
                "urgent_fee": urgent_fee,
            },
        )
        for source in ("BASE_DELIVERY", "UPSTAIRS", "MANUAL_EXTRA"):
            CommissionConfig.objects.get_or_create(
                business_type=business_type,
                earning_source=source,
            )
    for order, phrase in enumerate(
        ("快递架", "外卖架", "左侧", "右侧", "顶层", "最底层", "靠墙"), start=1
    ):
        QuickLocationPhrase.objects.get_or_create(
            text=phrase,
            defaults={"sort_order": order},
        )


class Migration(migrations.Migration):
    dependencies = [("config_center", "0002_alter_commissionconfig_commission_rate")]

    operations = [migrations.RunPython(seed_configuration, migrations.RunPython.noop)]
