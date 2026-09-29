"""Restore only missing V1 configuration rows without overwriting operator changes."""

from django.core.management.base import BaseCommand

from apps.config_center.models import (
    Building,
    BusinessTypeConfig,
    CommissionConfig,
    QuickLocationPhrase,
    SiteConfiguration,
)

BUSINESSES = [
    ("EXPRESS", "快递代取", "📦", "2.00", True, "1.00"),
    ("TAKEOUT", "校门口外卖", "🥡", "3.00", True, "2.00"),
    ("KFC", "周四 KFC", "🍗", "10.00", True, "5.00"),
    ("GROCERY", "果蔬零食", "🥬", "5.00", True, "2.00"),
    ("ERRAND", "跑腿送东西", "🏃", "3.00", True, "2.00"),
    ("LUGGAGE_UPSTAIRS", "行李搬上楼", "🧳", None, False, "0.00"),
]


class Command(BaseCommand):
    help = "Create missing fixed V1 configuration rows; never overwrite existing values."

    def handle(self, *args, **options):
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
        for sort_order, values in enumerate(BUSINESSES, start=1):
            business_type, name, icon, base, urgent_supported, urgent_fee = values
            BusinessTypeConfig.objects.get_or_create(
                business_type=business_type,
                defaults={
                    "display_name": name,
                    "icon": icon,
                    "sort_order": sort_order,
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
        for sort_order, phrase in enumerate(
            ("快递架", "外卖架", "左侧", "右侧", "顶层", "最底层", "靠墙"), start=1
        ):
            QuickLocationPhrase.objects.get_or_create(
                text=phrase,
                defaults={"sort_order": sort_order},
            )
        self.stdout.write(self.style.SUCCESS("V1 初始配置已核对；现有配置未被覆盖"))
