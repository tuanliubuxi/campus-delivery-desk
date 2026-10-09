"""Administrator views for customer search, creation, and editing."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.common.permissions import recorder_or_admin_required
from apps.config_center.models import Building, BusinessTypeConfig
from apps.customers.forms import CustomerForm
from apps.customers.models import Customer
from apps.customers.selectors import search_customers
from apps.customers.services import create_customer, delete_customer, update_customer


@recorder_or_admin_required
def customer_profile(request, customer_id):
    """Small same-origin payload used to prefill a new order without mutating master data."""
    customer = get_object_or_404(Customer.objects.select_related("building"), pk=customer_id)
    return JsonResponse(
        {
            "building_id": customer.building_id,
            "floor": customer.floor,
            "room": customer.room,
        }
    )


@recorder_or_admin_required
def customer_list(request):
    query = request.GET.get("q", "").strip()
    building_id = request.GET.get("building", "")
    activity = request.GET.get("activity", "")
    if not building_id.isdecimal() or not Building.objects.filter(pk=building_id).exists():
        building_id = ""
    if activity not in {"unfinished", "recent", "never"}:
        activity = ""
    page = Paginator(
        search_customers(query, building_id=building_id, activity=activity), 50
    ).get_page(request.GET.get("page"))
    return render(request, "customers/list.html", {
        "page": page,
        "query": query,
        "building_id": building_id,
        "activity": activity,
        "buildings": Building.objects.filter(is_active=True),
        "businesses": BusinessTypeConfig.objects.filter(enabled=True),
    })


@recorder_or_admin_required
def customer_picker(request):
    query = request.GET.get("q", "").strip()
    building_id = request.GET.get("building", "")
    if not query and not building_id:
        return JsonResponse({"results": [], "message": "请输入名称或手机号尾号，或选择楼栋"})
    if building_id and (not building_id.isdecimal() or not Building.objects.filter(pk=building_id).exists()):
        return JsonResponse({"results": [], "message": "楼栋无效"}, status=400)
    customers = search_customers(query, building_id=building_id)[:100]
    return JsonResponse({"results": [
        {
            "id": customer.pk,
            "name": customer.display_name,
            "recipients": customer.recipient_names,
            "phone": customer.phone_suffixes,
            "building": customer.building.name if customer.building else "地址待补",
        }
        for customer in customers
    ]})


@recorder_or_admin_required
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        duplicates = list(form.duplicate_candidates()[:5])
        customer = create_customer(actor=request.user, **form.cleaned_data)
        if duplicates:
            names = "、".join(item.display_name for item in duplicates)
            messages.warning(request, f"已创建；请留意疑似重复客户：{names}")
        else:
            messages.success(request, "客户已创建")
        return redirect("customers:edit", customer_id=customer.pk)
    return render(request, "customers/form.html", {"form": form, "title": "新建客户"})


@recorder_or_admin_required
def customer_edit(request, customer_id):
    customer = get_object_or_404(Customer.objects.select_related("building"), pk=customer_id)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        duplicates = list(form.duplicate_candidates()[:5])
        customer = update_customer(customer=customer, actor=request.user, **form.cleaned_data)
        if duplicates:
            names = "、".join(item.display_name for item in duplicates)
            messages.warning(request, f"已保存；请留意疑似重复客户：{names}")
        else:
            messages.success(request, "客户资料已保存；历史订单快照不受影响")
        return redirect("customers:edit", customer_id=customer.pk)
    return render(
        request,
        "customers/form.html",
        {"form": form, "title": "编辑客户", "customer": customer},
    )


@require_POST
@recorder_or_admin_required
def customer_delete(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    try:
        delete_customer(customer=customer, actor=request.user)
    except ProtectedError:
        messages.error(request, "该客户已有业务记录，不能删除；历史快照会继续保留")
    else:
        messages.success(request, "客户已删除")
    return redirect("customers:list")
