"""Thin recorder views delegating writes to order services."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from apps.agents.models import ProxyRecipient
from apps.common.enums import BusinessType
from apps.common.permissions import recorder_or_admin_required
from apps.config_center.models import Building, BusinessTypeConfig, SiteConfiguration
from apps.customers.models import Customer
from apps.orders.forms import (
    CancelOrderForm,
    ErrandOrderForm,
    ExpressOrderForm,
    GroceryOrderForm,
    KfcOrderForm,
    LuggageOrderForm,
    TakeoutOrderForm,
)
from apps.orders.models import DeliveryStatus, Order
from apps.orders.selectors import order_detail, search_orders
from apps.orders.services import (
    PossibleDuplicateOrder,
    cancel_order,
    create_errand_order,
    create_express_order,
    create_grocery_order,
    create_kfc_order,
    create_luggage_upstairs_order,
    create_takeout_order,
    update_order,
)

FORM_MAP = {
    BusinessType.EXPRESS: ExpressOrderForm,
    BusinessType.TAKEOUT: TakeoutOrderForm,
    BusinessType.KFC: KfcOrderForm,
    BusinessType.GROCERY: GroceryOrderForm,
    BusinessType.ERRAND: ErrandOrderForm,
    BusinessType.LUGGAGE_UPSTAIRS: LuggageOrderForm,
}
CREATOR_MAP = {
    BusinessType.EXPRESS: create_express_order,
    BusinessType.TAKEOUT: create_takeout_order,
    BusinessType.KFC: create_kfc_order,
    BusinessType.GROCERY: create_grocery_order,
    BusinessType.ERRAND: create_errand_order,
    BusinessType.LUGGAGE_UPSTAIRS: create_luggage_upstairs_order,
}
DETAIL_FIELDS = {
    BusinessType.EXPRESS: [
        "pickup_area",
        "outside_pickup_location",
        "pickup_identifier_type",
        "pickup_identifier",
        "size_class",
        "dispatch_mode",
    ],
    BusinessType.TAKEOUT: ["pickup_gate", "other_pickup_location", "identifier"],
    BusinessType.KFC: ["pickup_location", "pickup_code"],
    BusinessType.GROCERY: ["pickup_location", "item_list"],
    BusinessType.ERRAND: [
        "pickup_location",
        "delivery_location_text",
        "item_description",
        "size_class",
    ],
    BusinessType.LUGGAGE_UPSTAIRS: [
        "small_medium_count",
        "large_oversize_count",
        "floor",
        "special_pickup_note",
    ],
}


def _business_type(value):
    normalized = value.upper()
    if normalized not in FORM_MAP:
        raise ValueError("未知业务类型")
    return normalized


@recorder_or_admin_required
def order_new(request):
    businesses = BusinessTypeConfig.objects.filter(enabled=True)
    return render(request, "orders/chooser.html", {"businesses": businesses})


@recorder_or_admin_required
def order_create(request, business_type):
    try:
        business_type = _business_type(business_type)
    except ValueError:
        return redirect("orders:new")
    customer = None
    customer_id = request.GET.get("customer") or request.POST.get("continuous_customer")
    if customer_id:
        customer = get_object_or_404(Customer, pk=customer_id)
    form = FORM_MAP[business_type](request.POST or None, customer=customer)
    if request.method == "POST" and form.is_valid():
        try:
            order = CREATOR_MAP[business_type](actor=request.user, **form.service_kwargs())
        except PossibleDuplicateOrder as exc:
            form.add_error(
                "confirm_duplicate",
                f"发现 {len(exc.orders)} 条疑似重复订单；核对后可勾选确认继续。",
            )
        except (ValidationError, ValueError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"订单 {order.fixed_id} 已创建")
            if (
                business_type == BusinessType.KFC
                and order.sequence_date.isoweekday() != SiteConfiguration.load().kfc_open_weekday
            ):
                messages.warning(request, "当前不是配置的 KFC 开放日，请确认订单日期。")
            if request.POST.get("continue_entry"):
                return redirect(f"{request.path}?customer={order.customer_id}")
            return redirect("orders:detail", order_id=order.pk)
    return render(
        request,
        "orders/form.html",
        {"form": form, "business_type": business_type, "is_create": True},
    )


@recorder_or_admin_required
def continuous_entry(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    businesses = BusinessTypeConfig.objects.filter(enabled=True)
    return render(
        request,
        "orders/chooser.html",
        {"businesses": businesses, "continuous_customer": customer},
    )


@recorder_or_admin_required
def proxy_express_create(request, recipient_id):
    recipient = get_object_or_404(
        ProxyRecipient.objects.select_related("proxy_batch", "building"),
        pk=recipient_id,
    )
    form = ExpressOrderForm(request.POST or None, proxy_recipient=recipient)
    if request.method == "POST" and form.is_valid():
        try:
            order = create_express_order(actor=request.user, **form.service_kwargs())
        except PossibleDuplicateOrder as exc:
            form.add_error(
                "confirm_duplicate",
                f"发现 {len(exc.orders)} 条疑似重复订单；核对后可确认继续。",
            )
        except (ValidationError, ValueError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"代理快递 {order.fixed_id} 已创建")
            if request.POST.get("continue_entry"):
                return redirect("orders:proxy-express-create", recipient_id=recipient.pk)
            return redirect("agents:batch-detail", batch_id=recipient.proxy_batch_id)
    return render(
        request,
        "orders/form.html",
        {
            "form": form,
            "business_type": BusinessType.EXPRESS,
            "proxy_recipient": recipient,
            "is_create": True,
        },
    )


@recorder_or_admin_required
def order_history(request):
    query = request.GET.get("q", "").strip()
    page = Paginator(search_orders(query), 50).get_page(request.GET.get("page"))
    return render(request, "orders/history.html", {"page": page, "query": query})


@recorder_or_admin_required
def order_show(request, order_id):
    try:
        order = order_detail(order_id)
    except Order.DoesNotExist:
        order = get_object_or_404(search_orders(), pk=order_id)
    return render(request, "orders/detail.html", {"order": order})


def _edit_initial(order):
    detail = getattr(
        order,
        {
            BusinessType.EXPRESS: "express_detail",
            BusinessType.TAKEOUT: "takeout_detail",
            BusinessType.KFC: "kfc_detail",
            BusinessType.GROCERY: "grocery_detail",
            BusinessType.ERRAND: "errand_detail",
            BusinessType.LUGGAGE_UPSTAIRS: "luggage_detail",
        }[order.business_type],
    )
    initial = {
        "customer": order.customer,
        "service_date": order.service_date,
        "destination_type": order.destination_type,
        "building": Building.objects.filter(name=order.building_snapshot).first(),
        "floor": order.floor_snapshot,
        "room": order.room_snapshot,
        "off_campus_address": order.off_campus_address,
        "requires_upstairs": order.requires_upstairs,
        "is_urgent": order.is_urgent,
        "order_note": order.order_note,
    }
    for field in DETAIL_FIELDS[order.business_type]:
        initial[field] = getattr(detail, field)
    return initial, detail


@recorder_or_admin_required
def order_edit(request, order_id):
    order = order_detail(order_id)
    if order.delivery_status != DeliveryStatus.NEW:
        messages.error(request, "只有待接单订单可以修改")
        return redirect("orders:detail", order_id=order.pk)
    initial, detail = _edit_initial(order)
    form = FORM_MAP[order.business_type](
        request.POST or None,
        initial=initial,
        customer=order.customer,
        proxy_recipient=order.proxy_recipient,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        if not order.proxy_recipient and data["customer"] != order.customer:
            form.add_error("customer", "订单修改不能更换收件归属")
        else:
            detail_changes = {field: data[field] for field in DETAIL_FIELDS[order.business_type]}
            try:
                update_order(
                    order=order,
                    actor=request.user,
                    building=data["building"],
                    detail_changes=detail_changes,
                    service_date=data.get("service_date"),
                    is_urgent=data["is_urgent"],
                    requires_upstairs=data["requires_upstairs"],
                    destination_type=data["destination_type"],
                    floor_snapshot=data["floor"],
                    room_snapshot=data["room"],
                    off_campus_address=data["off_campus_address"],
                    order_note=data["order_note"],
                )
            except (ValidationError, ValueError) as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, f"订单 {order.fixed_id} 已更新")
                return redirect("orders:detail", order_id=order.pk)
    return render(
        request,
        "orders/form.html",
        {"form": form, "business_type": order.business_type, "order": order, "is_create": False},
    )


@recorder_or_admin_required
def order_cancel(request, order_id):
    order = order_detail(order_id)
    form = CancelOrderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            cancel_order(order=order, actor=request.user, reason=form.cleaned_data["reason"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"订单 {order.fixed_id} 已取消")
            return redirect("orders:detail", order_id=order.pk)
    return render(request, "orders/cancel.html", {"order": order, "form": form})
