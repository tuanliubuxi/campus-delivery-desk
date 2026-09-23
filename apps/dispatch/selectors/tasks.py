"""Courier task-pool and owned-task queries without template N+1 access."""

from django.db.models import Exists, OuterRef

from apps.orders.models import DeliveryStatus, Order

from ..models import Assignment, DeliveryTask, TaskStatus
from ..services.simple import SIMPLE_BUSINESSES


def simple_task_pool(courier):
    if courier.accepting_business not in SIMPLE_BUSINESSES:
        return Order.objects.none()
    active_assignment = Assignment.objects.filter(order_id=OuterRef("pk"), is_active=True)
    return (
        Order.objects.filter(
            business_type=courier.accepting_business,
            delivery_status=DeliveryStatus.NEW,
            source_type="DIRECT",
        )
        .annotate(has_active_assignment=Exists(active_assignment))
        .filter(has_active_assignment=False)
        .select_related("customer")
        .order_by("-is_urgent", "created_at", "id")
    )


def courier_tasks(courier, *, active_only=True):
    queryset = DeliveryTask.objects.filter(courier=courier).prefetch_related(
        "assignments__order__customer",
    )
    if active_only:
        queryset = queryset.filter(status=TaskStatus.ACTIVE)
    return queryset


def courier_task_detail(courier, task_id):
    return courier_tasks(courier, active_only=False).get(pk=task_id)
