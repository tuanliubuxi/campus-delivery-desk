"""SQLite-safe creation of the one OPEN ExpressRound for a recipient/date."""

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_event
from apps.orders.models import (
    DeliveryStatus,
    ExpressRound,
    ExpressRoundStatus,
    RecipientKind,
)


@transaction.atomic
def get_or_create_express_round(*, customer=None, proxy_recipient=None, service_date):
    if service_date is None:
        raise ValueError("快递 service_date 必填")
    if (customer is None) == (proxy_recipient is None):
        raise ValueError("ExpressRound 必须且只能绑定一种收件归属")
    lookup = {"service_date": service_date, "status": ExpressRoundStatus.OPEN}
    recipient_lookup = {"customer": customer} if customer else {"proxy_recipient": proxy_recipient}
    existing = ExpressRound.objects.filter(**lookup, **recipient_lookup).first()
    if existing:
        return existing

    all_rounds = ExpressRound.objects.filter(service_date=service_date, **recipient_lookup)
    next_round = (all_rounds.aggregate(Max("round_no"))["round_no__max"] or 0) + 1
    try:
        # A savepoint lets a concurrent creator lose the UNIQUE race without breaking the caller.
        with transaction.atomic():
            return ExpressRound.objects.create(
                recipient_kind=(
                    RecipientKind.CUSTOMER if customer else RecipientKind.PROXY_RECIPIENT
                ),
                customer=customer,
                proxy_recipient=proxy_recipient,
                service_date=service_date,
                round_no=next_round,
            )
    except IntegrityError:
        winner = ExpressRound.objects.filter(**lookup, **recipient_lookup).first()
        if winner:
            return winner
        raise


@transaction.atomic
def evaluate_express_round(*, express_round, actor=None):
    """Close trivial rounds or create/wait for each necessary consolidation round."""
    express_round = ExpressRound.objects.get(pk=express_round.pk)
    if express_round.status == ExpressRoundStatus.CLOSED:
        return express_round
    orders = express_round.express_details.values("order__delivery_status")
    if not orders.exists():
        return express_round
    active_states = {
        DeliveryStatus.NEW,
        DeliveryStatus.ASSIGNED,
        DeliveryStatus.PICKED,
        DeliveryStatus.DELIVERING,
    }
    if orders.filter(order__delivery_status__in=active_states).exists():
        return express_round
    delivered_count = orders.filter(order__delivery_status=DeliveryStatus.DELIVERED).count()
    if delivered_count >= 2:
        # Local imports preserve the intended orders -> consolidation dependency at runtime.
        from apps.consolidation.models import ConsolidationStatus
        from apps.consolidation.selectors import eligible_orders_for_round
        from apps.consolidation.services import create_consolidation_round

        pending = express_round.consolidation_rounds.filter(
            status__in=[ConsolidationStatus.PENDING, ConsolidationStatus.IN_PROGRESS]
        )
        if pending.exists():
            return express_round
        candidates = eligible_orders_for_round(express_round)
        if candidates.count() >= 2:
            create_consolidation_round(express_round=express_round, actor=actor)
            return express_round
    express_round.status = ExpressRoundStatus.CLOSED
    express_round.closed_at = timezone.now()
    express_round.save(update_fields=["status", "closed_at"])
    record_event(
        actor=actor,
        event_type="EXPRESS_ROUND_CLOSED",
        entity=express_round,
        metadata={"delivered_count": delivered_count},
    )
    return express_round
