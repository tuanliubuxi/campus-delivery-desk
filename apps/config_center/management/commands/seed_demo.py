"""Create an idempotent, visibly synthetic demonstration dataset in DEBUG only."""

import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.services.users import generate_password
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building
from apps.customers.models import Customer
from apps.orders.models import DestinationType, TakeoutGate
from apps.orders.services import create_takeout_order

DEMO_NAMESPACE = uuid.UUID("79bc457c-2086-4d77-bd09-a4b71b347ef4")


def _demo_user(*, username, display_name, role, emoji, password):
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "display_name": display_name,
            "role": role,
            "emoji_avatar": emoji,
            "is_staff": role == UserRole.ADMIN,
            "is_superuser": role == UserRole.ADMIN,
        },
    )
    if not created and user.role != role:
        raise CommandError(f"Demo 用户名 {username} 已被其他角色占用，未修改现有账号")
    if created:
        user.set_password(password)
        if role == UserRole.COURIER:
            user.accepting_business = BusinessType.TAKEOUT
        user.save()
    return user, created


class Command(BaseCommand):
    help = "Seed synthetic demo accounts, one customer, and one order; DEBUG environments only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            help="Optional shared demo password; omitted values are generated randomly.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo 仅允许在 DEBUG=true 的开发/演示环境运行")
        password = options["password"] or generate_password()
        admin, admin_created = _demo_user(
            username="demo-admin",
            display_name="演示管理员",
            role=UserRole.ADMIN,
            emoji="🛠️",
            password=password,
        )
        recorder, recorder_created = _demo_user(
            username="demo-recorder",
            display_name="演示录单员",
            role=UserRole.RECORDER,
            emoji="📝",
            password=password,
        )
        _, courier_created = _demo_user(
            username="demo-courier",
            display_name="演示配送员",
            role=UserRole.COURIER,
            emoji="🚴",
            password=password,
        )
        building = Building.objects.filter(code="1").first()
        if building is None:
            raise CommandError("缺少初始楼栋配置，请先运行 seed_initial_config")
        customer, _ = Customer.objects.get_or_create(
            wechat_nickname="【演示】小驿",
            defaults={
                "recipient_names": "演示收件人",
                "phone_suffixes": "0000",
                "building": building,
                "floor": "2",
                "room": "201",
                "long_term_note": "仅用于本地演示的合成数据",
                "created_by": admin,
            },
        )
        create_takeout_order(
            actor=recorder,
            operation_id=uuid.uuid5(DEMO_NAMESPACE, "takeout-order-1"),
            customer=customer,
            pickup_gate=TakeoutGate.SOUTH_GATE,
            identifier="演示订单-001",
            destination_type=DestinationType.CAMPUS_BUILDING,
            building=building,
            floor="2",
            room="201",
            order_note="仅用于功能演示",
        )
        self.stdout.write(self.style.SUCCESS("Demo 数据已就绪；重复执行不会重复创建订单"))
        if admin_created or recorder_created or courier_created:
            self.stdout.write(f"本次新建 Demo 账号的统一随机口令：{password}")
