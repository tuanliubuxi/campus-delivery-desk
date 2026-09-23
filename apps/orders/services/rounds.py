"""SQLite-safe creation of the one OPEN ExpressRound for a recipient/date."""

from django.db import IntegrityError, transaction
from django.db.models import Max

from apps.orders.models import ExpressRound, ExpressRoundStatus, RecipientKind


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
