"""Populate a disposable SQLite database and time representative V1 read paths."""

import gc
import json
import platform
import sqlite3
import statistics
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test.utils import override_settings
from django.utils import timezone

from apps.agents.models import Agent
from apps.agents.selectors import search_agents
from apps.common.enums import BusinessType
from apps.config_center.models import Building
from apps.customers.models import Customer
from apps.customers.selectors import search_customers
from apps.dashboard.selectors import DashboardFilters, dashboard_cards, dashboard_table
from apps.orders.models import (
    DeliveryStatus,
    DestinationType,
    DispatchMode,
    ExpressOrderDetail,
    ExpressRound,
    ExpressRoundStatus,
    Order,
    PickupArea,
    PickupIdentifierType,
    RecipientKind,
    SizeClass,
    SourceType,
)
from apps.orders.selectors import search_orders


class Command(BaseCommand):
    help = "Seed and benchmark a disposable V1 SQLite database at the documented scale."

    def add_arguments(self, parser):
        parser.add_argument("--customers", type=int, default=20_000)
        parser.add_argument("--agents", type=int, default=1_000)
        parser.add_argument("--orders", type=int, default=79_000)
        parser.add_argument("--batch-size", type=int, default=2_000)
        parser.add_argument("--repeats", type=int, default=3)
        parser.add_argument(
            "--confirm-disposable",
            action="store_true",
            help="Required acknowledgement that DB_PATH points to an empty throwaway database.",
        )

    def handle(self, *args, **options):
        counts = {name: options[name] for name in ("customers", "agents", "orders")}
        if not options["confirm_disposable"]:
            raise CommandError("必须显式传入 --confirm-disposable")
        if not settings.DEBUG:
            raise CommandError("性能基准只允许在 DEBUG 开发设置中运行")
        if any(value < 1 for value in counts.values()):
            raise CommandError("customers、agents、orders 必须均大于 0")
        if options["batch_size"] < 1 or options["repeats"] < 1:
            raise CommandError("batch-size 和 repeats 必须大于 0")
        database_path = Path(connection.settings_dict["NAME"]).resolve()
        default_database_path = (Path(settings.DATA_ROOT) / "db" / "app.sqlite3").resolve()
        if database_path == default_database_path:
            raise CommandError("DB_PATH 必须指向独立临时数据库，禁止使用默认 app.sqlite3")
        if Customer.objects.exists() or Agent.objects.exists() or Order.objects.exists():
            raise CommandError("基准数据库必须没有 Customer、Agent 或 Order 业务数据")

        building = Building.objects.order_by("route_order", "id").first()
        if building is None:
            raise CommandError("缺少初始楼栋配置，请先运行 seed_initial_config")

        started = time.perf_counter()
        customer_seconds = self._create_customers(counts["customers"], building, options["batch_size"])
        agent_seconds = self._create_agents(counts["agents"], options["batch_size"])
        round_seconds, order_seconds = self._create_orders(
            counts["orders"], building, options["batch_size"]
        )
        seed_seconds = time.perf_counter() - started

        # Run reads with production-like query logging disabled while retaining the
        # development-only safety gate checked above.
        with override_settings(DEBUG=False):
            timings = self._benchmark_reads(counts, options["repeats"])

        database_path = str(database_path)
        report = {
            "dataset": {
                **counts,
                "combined_customer_agent_order": sum(counts.values()),
                "express_rounds": ExpressRound.objects.count(),
                "express_details": ExpressOrderDetail.objects.count(),
            },
            "seed_seconds": {
                "customers": round(customer_seconds, 3),
                "agents": round(agent_seconds, 3),
                "rounds": round(round_seconds, 3),
                "orders_and_details": round(order_seconds, 3),
                "total": round(seed_seconds, 3),
            },
            "timings_ms": timings,
            "environment": {
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "platform": platform.platform(),
                "database": database_path,
                "database_bytes": self._database_size(database_path),
                "repeats": options["repeats"],
            },
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))

    @staticmethod
    def _create_customers(count, building, batch_size):
        started = time.perf_counter()
        for offset in range(0, count, batch_size):
            size = min(batch_size, count - offset)
            Customer.objects.bulk_create(
                [
                    Customer(
                        wechat_nickname=f"基准客户{index:06d}",
                        recipient_names=f"收件人{index:06d}",
                        phone_suffixes=f"{index % 10_000:04d}",
                        building=building,
                        floor=str(index % 8 + 1),
                        room=f"{index % 900 + 100}",
                    )
                    for index in range(offset, offset + size)
                ],
                batch_size=batch_size,
            )
        return time.perf_counter() - started

    @staticmethod
    def _create_agents(count, batch_size):
        started = time.perf_counter()
        for offset in range(0, count, batch_size):
            size = min(batch_size, count - offset)
            Agent.objects.bulk_create(
                [
                    Agent(name=f"基准代理{index:05d}", contact_text=f"contact-{index:05d}")
                    for index in range(offset, offset + size)
                ],
                batch_size=batch_size,
            )
        return time.perf_counter() - started

    @staticmethod
    def _create_orders(count, building, batch_size):
        customers = list(Customer.objects.order_by("id").values_list("id", flat=True))
        service_date = timezone.localdate()
        round_started = time.perf_counter()
        rounds = ExpressRound.objects.bulk_create(
            [
                ExpressRound(
                    recipient_kind=RecipientKind.CUSTOMER,
                    customer_id=customer_id,
                    service_date=service_date,
                    round_no=1,
                    status=ExpressRoundStatus.CLOSED,
                    closed_at=timezone.now(),
                )
                for customer_id in customers
            ],
            batch_size=batch_size,
        )
        round_seconds = time.perf_counter() - round_started
        round_ids = [item.pk for item in rounds]

        order_started = time.perf_counter()
        for offset in range(0, count, batch_size):
            size = min(batch_size, count - offset)
            orders = []
            for index in range(offset, offset + size):
                customer_index = index % len(customers)
                orders.append(
                    Order(
                        business_type=BusinessType.EXPRESS,
                        sequence_date=service_date,
                        daily_sequence=index + 1,
                        service_date=service_date,
                        source_type=SourceType.DIRECT,
                        customer_id=customers[customer_index],
                        delivery_status=(
                            DeliveryStatus.DELIVERED if index % 2 else DeliveryStatus.NEW
                        ),
                        destination_type=DestinationType.CAMPUS_BUILDING,
                        building_snapshot=building.name,
                        zone_snapshot=building.zone,
                        floor_snapshot=str(index % 8 + 1),
                        room_snapshot=f"{index % 900 + 100}",
                        recipient_name_snapshot=f"收件人{customer_index:06d}",
                        recipient_phone_snapshot=f"{customer_index % 10_000:04d}",
                        is_urgent=index % 20 == 0,
                    )
                )
            Order.objects.bulk_create(orders, batch_size=batch_size)
            ExpressOrderDetail.objects.bulk_create(
                [
                    ExpressOrderDetail(
                        order_id=order.pk,
                        express_round_id=round_ids[(offset + index) % len(round_ids)],
                        pickup_area=(
                            PickupArea.SOUTH if (offset + index) % 2 else PickupArea.NORTH
                        ),
                        pickup_identifier_type=PickupIdentifierType.PICKUP_CODE,
                        pickup_identifier=f"BENCH-{offset + index:08d}",
                        normalized_pickup_identifier=f"BENCH{offset + index:08d}",
                        size_class=SizeClass.SMALL,
                        dispatch_mode=DispatchMode.ROUTE,
                        small_price_snapshot=Decimal("2.00"),
                        medium_price_snapshot=Decimal("4.00"),
                        large_price_snapshot=Decimal("6.00"),
                        oversize_price_snapshot=Decimal("8.00"),
                    )
                    for index, order in enumerate(orders)
                ],
                batch_size=batch_size,
            )
        return round_seconds, time.perf_counter() - order_started

    @staticmethod
    def _measure(callback, repeats):
        callback()
        samples = []
        for _ in range(repeats):
            gc.collect()
            started = time.perf_counter()
            callback()
            samples.append((time.perf_counter() - started) * 1_000)
        return {
            "min": round(min(samples), 2),
            "median": round(statistics.median(samples), 2),
            "max": round(max(samples), 2),
        }

    def _benchmark_reads(self, counts, repeats):
        last_order = Order.objects.order_by("-id").first()
        exact_order_id = last_order.fixed_id
        pickup_query = f"BENCH{counts['orders'] - 1:08d}"
        filters = DashboardFilters(date_from=timezone.localdate() - timedelta(days=1))
        cases = {
            "customers_page_50": lambda: list(search_customers()[:50]),
            "customer_text_search": lambda: list(
                search_customers(f"基准客户{counts['customers'] - 1:06d}")[:50]
            ),
            "agents_page_50": lambda: list(search_agents()[:50]),
            "agent_text_search": lambda: list(
                search_agents(f"基准代理{counts['agents'] - 1:05d}")[:50]
            ),
            "orders_page_50": lambda: list(search_orders()[:50]),
            "order_exact_id": lambda: list(search_orders(exact_order_id)[:1]),
            "order_pickup_identifier": lambda: list(search_orders(pickup_query)[:50]),
            "dashboard_table_50": lambda: list(dashboard_table(filters, limit=50)),
            "dashboard_cards": lambda: dashboard_cards(filters),
        }
        return {name: self._measure(callback, repeats) for name, callback in cases.items()}

    @staticmethod
    def _database_size(database_path):
        try:
            return Path(database_path).stat().st_size
        except OSError:
            return None
