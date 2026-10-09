"""Permission and audit boundary for pre-settlement proxy delivery receipts."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.agents.selectors.proxy import proxy_delivery_receipt_readiness
from apps.audit.services import record_event

from .build import require_financial_operator
from .receipts import create_proxy_delivery_receipt


@transaction.atomic
def generate_proxy_recipient_receipt(*, recipient, actor):
    require_financial_operator(actor)
    reasons = proxy_delivery_receipt_readiness(recipient)
    if reasons:
        raise ValidationError("暂不能生成配送凭证：" + "；".join(reasons))
    receipt = create_proxy_delivery_receipt(recipient=recipient)
    record_event(
        actor=actor,
        event_type="PROXY_RECIPIENT_RECEIPT_GENERATED",
        entity=receipt,
        metadata={
            "proxy_batch_id": recipient.proxy_batch_id,
            "show_price": receipt.show_price,
        },
    )
    return receipt
