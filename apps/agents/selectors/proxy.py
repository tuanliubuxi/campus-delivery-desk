"""Search and detail queries for agents, batches, and temporary recipients."""

from django.db.models import Count, Prefetch, Q

from apps.agents.models import Agent, ProxyBatch, ProxyRecipient


def search_agents(query=""):
    queryset = Agent.objects.annotate(batch_count=Count("proxy_batches", distinct=True))
    query = query.strip()
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query)
            | Q(contact_text__icontains=query)
            | Q(note__icontains=query)
            | Q(proxy_batches__recipients__display_name__icontains=query)
            | Q(proxy_batches__recipients__recipient_names__icontains=query)
            | Q(proxy_batches__recipients__phone_suffixes__icontains=query)
        ).distinct()
    return queryset


def search_proxy_batches(query=""):
    queryset = ProxyBatch.objects.select_related("agent", "created_by").annotate(
        recipient_count=Count("recipients", distinct=True)
    ).order_by("-batch_date", "-sequence", "-id")
    query = query.strip()
    if query:
        condition = (
            Q(agent__name__icontains=query)
            | Q(agent__contact_text__icontains=query)
            | Q(note__icontains=query)
            | Q(recipients__display_name__icontains=query)
            | Q(recipients__recipient_names__icontains=query)
            | Q(recipients__wechat_nickname__icontains=query)
            | Q(recipients__phone_suffixes__icontains=query)
        )
        if query.isdigit():
            condition |= Q(pk=int(query))
        queryset = queryset.filter(condition).distinct()
    return queryset


def proxy_batch_detail(batch_id):
    recipients = ProxyRecipient.objects.select_related("building").order_by("created_at", "id")
    return (
        ProxyBatch.objects.select_related("agent", "created_by")
        .prefetch_related(Prefetch("recipients", queryset=recipients))
        .get(pk=batch_id)
    )
