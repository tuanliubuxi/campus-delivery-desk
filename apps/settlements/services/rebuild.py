"""Audited regeneration of settlement artifacts from immutable structured facts."""

from django.db import transaction

from apps.audit.services import record_event
from apps.settlements.models import SettlementPartyType

from .build import require_financial_operator
from .receipts import (
    create_agent_summary_image,
    create_customer_settlement_image,
    create_proxy_recipient_receipt,
    receipt_photo_mode,
)


@transaction.atomic
def rebuild_settlement_artifacts(*, settlement, actor):
    """Rebuild full receipts when photos exist, otherwise explicit historical receipts."""
    require_financial_operator(actor)
    orders = settlement.settlement_orders.values_list("order_id", flat=True)
    from apps.orders.models import Order

    order_qs = Order.objects.filter(pk__in=orders)
    mode = receipt_photo_mode(order_qs)
    artifacts = []
    if settlement.party_type == SettlementPartyType.CUSTOMER:
        artifacts.append(create_customer_settlement_image(settlement))
    else:
        for recipient in settlement.proxy_batch.recipients.all():
            if recipient.orders.filter(settlement_orders__settlement=settlement).exists():
                artifacts.append(
                    create_proxy_recipient_receipt(settlement=settlement, recipient=recipient)
                )
        artifacts.append(create_agent_summary_image(settlement))
    record_event(
        actor=actor,
        event_type="SETTLEMENT_ARTIFACTS_REBUILT",
        entity=settlement,
        metadata={"mode": mode, "artifact_count": len(artifacts)},
    )
    return artifacts, mode
