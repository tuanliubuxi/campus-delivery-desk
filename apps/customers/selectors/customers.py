"""Customer search and possible-duplicate detection queries."""

import re
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.customers.models import Customer


def split_search_tokens(value):
    return [token.strip() for token in re.split(r"[/\s]+", value or "") if token.strip()]


def search_customers(query="", *, building_id=None, activity=""):
    customers = Customer.objects.select_related("building")
    if building_id:
        customers = customers.filter(building_id=building_id)
    if activity == "unfinished":
        customers = customers.filter(
            orders__delivery_status__in=["NEW", "ASSIGNED", "PICKED", "DELIVERING"]
        )
    elif activity == "recent":
        customers = customers.filter(
            orders__created_at__gte=timezone.now() - timedelta(days=30)
        )
    elif activity == "never":
        customers = customers.filter(orders__isnull=True)
    tokens = split_search_tokens(query)
    if not tokens:
        return customers.distinct()
    condition = Q()
    # Slash-separated input is an OR search: any known name or phone suffix can identify a customer.
    for token in tokens:
        condition |= (
            Q(wechat_nickname__icontains=token)
            | Q(recipient_names__icontains=token)
            | Q(phone_suffixes__icontains=token)
        )
    return customers.filter(condition).distinct()


def possible_duplicate_customers(*, wechat_nickname="", recipient_names="", phone_suffixes="", exclude_id=None):
    terms = split_search_tokens("/".join([wechat_nickname, recipient_names, phone_suffixes]))
    if not terms:
        return Customer.objects.none()
    condition = Q()
    for term in terms:
        condition |= (
            Q(wechat_nickname__iexact=term)
            | Q(recipient_names__icontains=term)
            | Q(phone_suffixes__icontains=term)
        )
    result = Customer.objects.filter(condition)
    return result.exclude(pk=exclude_id) if exclude_id else result
