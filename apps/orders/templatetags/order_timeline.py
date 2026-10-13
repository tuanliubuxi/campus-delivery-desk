"""Fact-only order timeline for each detail dialog, including historical orders."""

from django import template

from apps.audit.models import AuditEvent
from apps.dispatch.models import Assignment, DeliveryDropItem
from apps.settlements.models import SettlementOrder

register = template.Library()


@register.simple_tag
def order_timeline(order):
    def actor_text(user):
        return f"操作人：{user.display_name}" if user else "操作人未记录"

    rows = [(order.created_at, "录入订单", actor_text(order.created_by))]
    assignments = list(
        Assignment.objects.filter(order=order)
        .select_related("courier", "task")
        .order_by("assigned_at")
    )
    for assignment in assignments:
        name = str(assignment.courier)
        rows.append((assignment.assigned_at, "分配配送员", f"{name} · {actor_text(assignment.courier)}"))
        rows.append((assignment.task.accepted_at, "配送员接单", actor_text(assignment.courier)))
    order_event_labels = {
        "ORDER_PICKED": "确认取件", "EXPRESS_PICKED": "确认取件",
        "ORDER_UPDATED": "修改订单", "ORDER_CANCELED": "取消订单",
        "ORDER_RETURNED_TO_POOL": "退回任务池",
        "EXPRESS_SIZE_CONFIRMED": "核对快递大小",
        "ORDER_UPSTAIRS_CONFIRMED": "确认上楼件数",
        "ORDER_COMPLETED_DURING_ENTRY": "录入并完成配送",
    }
    order_events = AuditEvent.objects.filter(
        entity_type="orders.Order",
        entity_id=str(order.pk),
        event_type__in=order_event_labels,
    ).select_related("actor")
    rows.extend((event.created_at, order_event_labels[event.event_type], actor_text(event.actor)) for event in order_events)
    task_ids = {assignment.task_id for assignment in assignments}
    if task_ids:
        starts = AuditEvent.objects.filter(
            entity_type="dispatch.DeliveryTask",
            entity_id__in=[str(task_id) for task_id in task_ids],
            event_type="SIMPLE_DELIVERY_STARTED",
        ).select_related("actor")
        rows.extend((event.created_at, "开始配送", actor_text(event.actor)) for event in starts)
    for link in DeliveryDropItem.objects.filter(order=order).select_related("drop__courier"):
        rows.append((link.drop.delivered_at, "完成配送", actor_text(link.drop.courier)))
    members = list(SettlementOrder.objects.filter(order=order).select_related(
        "settlement__settled_by"
    ))
    freeze_events = {
        event.entity_id: event.actor
        for event in AuditEvent.objects.filter(
            entity_type="settlements.Settlement",
            entity_id__in=[str(member.settlement_id) for member in members],
            event_type="SETTLEMENT_FROZEN",
        ).select_related("actor")
    }
    for member in members:
        settlement = member.settlement
        if settlement.frozen_at:
            rows.append((settlement.frozen_at, "结算冻结", actor_text(
                freeze_events.get(str(settlement.pk))
            )))
        if settlement.settled_at:
            rows.append((settlement.settled_at, "确认收款", actor_text(settlement.settled_by)))
    return sorted((row for row in rows if row[0]), key=lambda row: row[0])
