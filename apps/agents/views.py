"""Thin recorder/admin views for the proxy intake workspace."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from apps.agents.forms import AgentEditForm, AgentForm, ProxyBatchForm, ProxyRecipientForm
from apps.agents.models import Agent, ProxyBatch, ProxyRecipient
from apps.agents.selectors import proxy_batch_detail, search_agents, search_proxy_batches
from apps.agents.services import (
    cancel_proxy_batch,
    create_agent,
    create_proxy_batch,
    create_proxy_recipient,
    delete_agent,
    delete_proxy_recipient,
    reopen_proxy_batch,
    update_agent,
    update_proxy_recipient,
)
from apps.common.pagination import paginate
from apps.common.permissions import recorder_or_admin_required
from apps.settlements.services import (
    generate_proxy_recipient_receipt,
    rebuild_proxy_settlement_receipt,
)


@recorder_or_admin_required
def proxy_workspace(request):
    query = request.GET.get("q", "").strip()
    batch_page = Paginator(search_proxy_batches(query), 50).get_page(request.GET.get("page"))
    agent_page, agent_query = paginate(request, search_agents(query), parameter="agent_page")
    return render(
        request,
        "agents/workspace.html",
        {"batch_page": batch_page, "agents": agent_page, "agent_page": agent_page, "agent_query": agent_query, "query": query},
    )


@recorder_or_admin_required
def agent_create(request):
    form = AgentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            agent = create_agent(actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error("name", exc)
        else:
            messages.success(request, f"代理人“{agent.name}”已创建")
            return redirect(f"{reverse('agents:batch-create')}?agent={agent.pk}")
    return render(request, "agents/form.html", {"form": form, "title": "新建代理人"})


@recorder_or_admin_required
def agent_edit(request, agent_id):
    agent = get_object_or_404(Agent, pk=agent_id)
    form = AgentEditForm(request.POST or None, instance=agent)
    if request.method == "POST" and form.is_valid():
        try:
            agent = update_agent(
                actor=request.user, agent=agent, is_active=agent.is_active, **form.cleaned_data
            )
        except ValidationError as exc:
            form.add_error("name", exc)
        else:
            messages.success(request, f"代理人“{agent.name}”已更新")
            return redirect("agents:workspace")
    return render(
        request,
        "agents/form.html",
        {"form": form, "title": "编辑代理人", "agent": agent},
    )


@require_POST
@recorder_or_admin_required
def agent_delete(request, agent_id):
    agent = get_object_or_404(Agent, pk=agent_id)
    try:
        delete_agent(actor=request.user, agent=agent)
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "代理人已删除")
    return redirect("agents:workspace")


@require_POST
@recorder_or_admin_required
def agent_toggle(request, agent_id):
    agent = get_object_or_404(Agent, pk=agent_id)
    active = request.POST.get("is_active") == "on"
    try:
        update_agent(
            actor=request.user,
            agent=agent,
            name=agent.name,
            contact_text=agent.contact_text,
            note=agent.note,
            is_active=active,
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        if active:
            messages.success(request, format_html(
                "代理人 <span class='cdd-detail-key cdd-detail-key--person'>{}</span> 已启用<br>可新建批次",
                agent.name,
            ))
        else:
            messages.success(request, format_html(
                "代理人 <span class='cdd-detail-key cdd-detail-key--person'>{}</span> 已停用",
                agent.name,
            ))
    return redirect("agents:workspace")


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
    from apps.agents.selectors.proxy import (
        proxy_batch_readiness,
        proxy_delivery_receipt_readiness,
    )

    for recipient in batch.recipients.all():
        recipient.delivery_receipt_reasons = proxy_delivery_receipt_readiness(recipient)
        recipient.has_delivery_receipt = False
        recipient.has_settlement_receipt = False
        for receipt in recipient.receipts.all():
            receipt.dialog_id = f"recipient-receipt-{receipt.pk}"
            if receipt.kind == receipt.Kind.DELIVERY:
                recipient.has_delivery_receipt = True
            else:
                recipient.has_settlement_receipt = True

    from_order_id = request.GET.get("from_order", "")
    from_order = (
        batch.orders.filter(pk=from_order_id).first()
        if from_order_id.isdecimal()
        else None
    )

    return render(
        request,
        "agents/batch_detail.html",
        {
            "batch": batch,
            "from_order": from_order,
            "readiness_reasons": proxy_batch_readiness(batch)
            if batch.status == "OPEN"
            else [],
        },
    )


@recorder_or_admin_required
def recipient_receipt_evidence(request, recipient_id):
    recipient = get_object_or_404(ProxyRecipient, pk=recipient_id)
    from apps.orders.models import Order
    from apps.settlements.services.receipts import _receipt_photo_state

    available_evidence, _ = _receipt_photo_state(Order.objects.filter(proxy_recipient=recipient))
    return render(request, "includes/receipt_evidence.html", {"available_evidence": available_evidence})


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
        messages.success(request, "临时收件人配送凭证已生成；最终金额请以结算凭证为准")
    return redirect("agents:batch-detail", batch_id=recipient.proxy_batch_id)


@require_POST
@recorder_or_admin_required
def recipient_rebuild_settlement_receipt(request, recipient_id):
    recipient = get_object_or_404(ProxyRecipient, pk=recipient_id)
    try:
        rebuild_proxy_settlement_receipt(recipient=recipient, actor=request.user)
    except (ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "临时收件人结算凭证已重建；配送凭证保持不变")
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


@require_POST
@recorder_or_admin_required
def recipient_delete(request, recipient_id):
    recipient = get_object_or_404(
        ProxyRecipient.objects.select_related("proxy_batch"), pk=recipient_id
    )
    batch_id = recipient.proxy_batch_id
    try:
        delete_proxy_recipient(actor=request.user, recipient=recipient)
    except (ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "空临时收件人已删除")
    return redirect("agents:batch-detail", batch_id=batch_id)
