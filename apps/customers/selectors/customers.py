import re

from django.db.models import Q

from apps.customers.models import Customer


def split_search_tokens(value):
    return [token.strip() for token in re.split(r"[/\s]+", value or "") if token.strip()]


def search_customers(query=""):
    customers = Customer.objects.select_related("building")
    tokens = split_search_tokens(query)
    if not tokens:
        return customers
    condition = Q()
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
