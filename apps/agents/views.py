"""Thin recorder/admin views for the proxy intake workspace."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.agents.forms import AgentEditForm, AgentForm, ProxyBatchForm, ProxyRecipientForm
from apps.agents.models import Agent, ProxyBatch, ProxyRecipient
from apps.agents.selectors import proxy_batch_detail, search_agents, search_proxy_batches
from apps.agents.services import (
    cancel_proxy_batch,
    create_agent,
    create_proxy_batch,
    create_proxy_recipient,
    reopen_proxy_batch,
    update_agent,
    update_proxy_recipient,
)
from apps.common.permissions import recorder_or_admin_required
from apps.settlements.services import generate_proxy_recipient_receipt


@recorder_or_admin_required
def proxy_workspace(request):
    query = request.GET.get("q", "").strip()
    batch_page = Paginator(search_proxy_batches(query), 50).get_page(request.GET.get("page"))
    agents = search_agents(query)[:20]
    return render(
        request,
        "agents/workspace.html",
        {"batch_page": batch_page, "agents": agents, "query": query},
    )


@recorder_or_admin_required
def agent_create(request):
    form = AgentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        agent = create_agent(actor=request.user, **form.cleaned_data)
        messages.success(request, f"代理人“{agent.name}”已创建")
        return redirect("agents:batch-create", agent=agent.pk)
    return render(request, "agents/form.html", {"form": form, "title": "新建代理人"})


@recorder_or_admin_required
def agent_edit(request, agent_id):
    agent = get_object_or_404(Agent, pk=agent_id)
    form = AgentEditForm(request.POST or None, instance=agent)
    if request.method == "POST" and form.is_valid():
        agent = update_agent(actor=request.user, agent=agent, **form.cleaned_data)
        messages.success(request, f"代理人“{agent.name}”已更新")
        return redirect("agents:workspace")
    return render(
        request,
        "agents/form.html",
        {"form": form, "title": "编辑代理人", "agent": agent},
    )


@recorder_or_admin_required
def batch_create(request):
    initial = {"agent": request.GET.get("agent", "")}
    form = ProxyBatchForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            batch = create_proxy_batch(actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "代理批次已创建；现在可以连续添加临时收件人")
            return redirect("agents:batch-detail", batch_id=batch.pk)
    return render(request, "agents/form.html", {"form": form, "title": "新建代理批次"})


@recorder_or_admin_required
def batch_detail(request, batch_id):
    try:
        batch = proxy_batch_detail(batch_id)
    except ProxyBatch.DoesNotExist:
        batch = get_object_or_404(ProxyBatch, pk=batch_id)
    return render(request, "agents/batch_detail.html", {"batch": batch})


@require_POST
@recorder_or_admin_required
def batch_cancel(request, batch_id):
    batch = get_object_or_404(ProxyBatch, pk=batch_id)
    try:
        cancel_proxy_batch(
            proxy_batch=batch,
            operator=request.user,
            reason=request.POST.get("reason", ""),
        )
    except (ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "代理批次及其中所有可取消快递已原子取消")
    return redirect("agents:batch-detail", batch_id=batch.pk)


@require_POST
@recorder_or_admin_required
def batch_reopen(request, batch_id):
    batch = get_object_or_404(ProxyBatch, pk=batch_id)
    try:
        reopen_proxy_batch(proxy_batch=batch, operator=request.user)
    except (ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "代理批次已重新打开，未结算凭证版本已失效")
    return redirect("agents:batch-detail", batch_id=batch.pk)


@require_POST
@recorder_or_admin_required
def recipient_generate_receipt(request, recipient_id):
    recipient = get_object_or_404(ProxyRecipient, pk=recipient_id)
    try:
        generate_proxy_recipient_receipt(recipient=recipient, actor=request.user)
    except (ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "临时收件人客户凭证已生成；批次状态未改变")
    return redirect("agents:batch-detail", batch_id=recipient.proxy_batch_id)


@recorder_or_admin_required
def recipient_create(request, batch_id):
    batch = get_object_or_404(ProxyBatch.objects.select_related("agent"), pk=batch_id)
    form = ProxyRecipientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            recipient = create_proxy_recipient(
                actor=request.user,
                proxy_batch=batch,
                **form.cleaned_data,
            )
        except (ValidationError, ValueError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"临时收件人“{recipient.display_name}”已加入批次")
            return redirect("agents:batch-detail", batch_id=batch.pk)
    return render(
        request,
        "agents/recipient_form.html",
        {"batch": batch, "form": form},
    )


@recorder_or_admin_required
def recipient_edit(request, recipient_id):
    recipient = get_object_or_404(
        ProxyRecipient.objects.select_related("proxy_batch", "proxy_batch__agent"),
        pk=recipient_id,
    )
    form = ProxyRecipientForm(request.POST or None, instance=recipient)
    if request.method == "POST" and form.is_valid():
        try:
            recipient = update_proxy_recipient(
                actor=request.user,
                recipient=recipient,
                **form.cleaned_data,
            )
        except (ValidationError, ValueError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"临时收件人“{recipient.display_name}”已更新")
            return redirect("agents:batch-detail", batch_id=recipient.proxy_batch_id)
    return render(
        request,
        "agents/recipient_form.html",
        {"batch": recipient.proxy_batch, "form": form, "recipient": recipient},
    )
