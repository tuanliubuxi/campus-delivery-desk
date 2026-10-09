"""Fact-only order timeline for each detail dialog, including historical orders."""

from django import template

from apps.audit.models import AuditEvent
from apps.dispatch.models import Assignment, DeliveryDropItem
from apps.settlements.models import SettlementOrder

register = template.Library()


@register.simple_tag
def order_timeline(order):
    rows = [(order.created_at, "录入订单", "")]
    assignments = list(
        Assignment.objects.filter(order=order)
        .select_related("courier", "task")
        .order_by("assigned_at")
    )
    for assignment in assignments:
        name = str(assignment.courier)
        rows.append((assignment.assigned_at, "分配配送员", name))
        rows.append((assignment.task.accepted_at, "配送员接单", name))
    order_events = AuditEvent.objects.filter(
        entity_type="orders.Order",
        entity_id=str(order.pk),
        event_type__in=["ORDER_PICKED", "EXPRESS_PICKED"],
    )
    rows.extend((event.created_at, "确认取件", "") for event in order_events)
    task_ids = {assignment.task_id for assignment in assignments}
    if task_ids:
        starts = AuditEvent.objects.filter(
            entity_type="dispatch.DeliveryTask",
            entity_id__in=[str(task_id) for task_id in task_ids],
            event_type="SIMPLE_DELIVERY_STARTED",
        )
        rows.extend((event.created_at, "开始配送", "") for event in starts)
    for link in DeliveryDropItem.objects.filter(order=order).select_related("drop__courier"):
        rows.append((link.drop.delivered_at, "完成配送", str(link.drop.courier)))
    for member in SettlementOrder.objects.filter(order=order).select_related("settlement"):
        settlement = member.settlement
        if settlement.frozen_at:
            rows.append((settlement.frozen_at, "结算冻结", ""))
        if settlement.settled_at:
            rows.append((settlement.settled_at, "确认收款", ""))
    return sorted((row for row in rows if row[0]), key=lambda row: row[0])
