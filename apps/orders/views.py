"""Thin recorder views delegating writes to order services."""

import json

from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.agents.models import ProxyRecipient
from apps.common.enums import BusinessType
from apps.common.permissions import recorder_or_admin_required
from apps.config_center.models import Building, BusinessTypeConfig, SiteConfiguration
from apps.customers.models import Customer
from apps.orders.forms import (
    CancelOrderForm,
    CompletionMetadataForm,
    ErrandOrderForm,
    ExpressOrderForm,
    GroceryOrderForm,
    KfcOrderForm,
    LuggageOrderForm,
    TakeoutOrderForm,
)
from apps.orders.models import DeliveryStatus, EntryMode, Order, SizeClass
from apps.orders.selectors import order_detail, search_orders
from apps.orders.services import (
    PossibleDuplicateOrder,
    cancel_order,
    create_completed_order,
    create_errand_order,
    create_express_order,
    create_grocery_order,
    create_kfc_order,
    create_luggage_upstairs_order,
    create_takeout_order,
    update_order,
)
from apps.orders.services.bulk import create_express_orders

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

ORDER_SECTION_FIELDS = (
    ("收件与日期", "identity", {"customer", "service_date"}),
    ("目的地", "destination", {"destination_type", "building", "floor", "room", "off_campus_address"}),
    ("取件与物品信息", "business", {
        "pickup_area", "outside_pickup_location", "pickup_gate", "other_pickup_location",
        "pickup_location", "pickup_identifier_type", "size_class", "pickup_identifier",
        "identifier", "pickup_code", "item_list", "item_description",
        "delivery_location_text", "small_medium_count", "large_oversize_count",
        "special_pickup_note",
    }),
    ("服务要求与备注", "service", {
        "requires_upstairs", "is_urgent", "upstairs_small_medium_count",
        "upstairs_large_oversize_count", "confirm_off_campus_upstairs", "order_note",
    }),
)


def _order_sections(form):
    visible = {field.name: field for field in form.visible_fields()}
    sections = []
    for title, tone, names in ORDER_SECTION_FIELDS:
        fields = [field for name, field in visible.items() if name in names]
        if fields:
            sections.append({"title": title, "tone": tone, "fields": fields})
    return sections


def _duplicate_payload(request, business_type):
    excluded = {"csrfmiddlewaretoken", "confirm_duplicate", "duplicate_review_token"}
    return {
        "actor_id": request.user.pk,
        "business_type": business_type,
        "fields": sorted([name, values] for name, values in request.POST.lists() if name not in excluded),
    }


def _duplicate_review_token(request, business_type):
    return signing.dumps(_duplicate_payload(request, business_type), salt="order-duplicate-review")


def _duplicate_review_valid(request, business_type):
    token = request.POST.get("duplicate_review_token", "")
    if not token:
        return False
    try:
        return signing.loads(token, salt="order-duplicate-review", max_age=1800) == _duplicate_payload(request, business_type)
    except signing.BadSignature:
        return False


DETAIL_FIELDS = {
    BusinessType.EXPRESS: [
        "pickup_area",
        "outside_pickup_location",
        "pickup_identifier_type",
        "pickup_identifier",
        "size_class",
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


def _entry_post_data(post, business_type):
    """Populate legacy single-item fields from the first typed editor row."""
    if post is None:
        return None
    data = post.copy()
    if business_type == BusinessType.EXPRESS:
        data.setdefault("pickup_identifier_type", "OTHER")
    raw = data.get("entry_items", "")
    if not raw:
        return data
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return data
    if not isinstance(items, list) or not items:
        return data
    first = items[0]
    if business_type == BusinessType.EXPRESS and isinstance(first, dict):
        for key in ("pickup_area", "outside_pickup_location", "pickup_identifier", "size_class"):
            if isinstance(first.get(key), str):
                data[key] = first[key]
    elif business_type == BusinessType.TAKEOUT and isinstance(first, str):
        data["identifier"] = first
    elif business_type == BusinessType.KFC and isinstance(first, str):
        data["pickup_code"] = first
    return data


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
    form = FORM_MAP[business_type](_entry_post_data(request.POST, business_type) if request.method == "POST" else None, customer=customer)
    duplicate_review = _duplicate_review_valid(request, business_type) if request.method == "POST" else False
    duplicate_token = request.POST.get("duplicate_review_token", "") if duplicate_review else ""
    duplicate_candidates = []
    if request.method == "POST" and form.is_valid():
        form.cleaned_data["confirm_duplicate"] = bool(form.cleaned_data["confirm_duplicate"] and duplicate_review)
        try:
            data = form.service_kwargs()
            items = form.cleaned_data.get("entry_items")
            if business_type == BusinessType.EXPRESS and items:
                orders = create_express_orders(actor=request.user, common_data=data, items=items)
                order = orders[0]
            else:
                if business_type == BusinessType.TAKEOUT and items:
                    data["identifiers"] = items
                elif business_type == BusinessType.KFC and items:
                    data["pickup_codes"] = items
                order = CREATOR_MAP[business_type](actor=request.user, **data)
        except PossibleDuplicateOrder as exc:
            duplicate_candidates = exc.orders
            duplicate_token = _duplicate_review_token(request, business_type)
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
        {
            "form": form,
            "item_form": form,
            "order_sections": _order_sections(form),
            "duplicate_token": duplicate_token,
            "duplicate_candidates": duplicate_candidates,
            "business_type": business_type,
            "express_areas": [("NORTH", "北区"), ("SOUTH", "南区"), ("OUTSIDE", "校外")],
            "business_label": BusinessType(business_type).label,
            "is_create": True,
            "selected_customer_id": customer.pk if customer else None,
            "customer_entry": request.GET.get("entry", "")[:32] if request.GET.get("entry", "").isdigit() else "",
            "picker_buildings": Building.objects.filter(is_active=True),
        },
    )


@recorder_or_admin_required
def quick_complete(request):
    """Render business-specific fields plus the explicit real-world completion facts."""
    business_value = request.POST.get("business_type") or request.GET.get("business_type")
    if not business_value:
        return render(
            request,
            "orders/quick_complete.html",
            {"businesses": BusinessTypeConfig.objects.filter(enabled=True)},
        )
    try:
        business_type = _business_type(business_value)
    except ValueError:
        return redirect("orders:quick-complete")
    customer_id = request.GET.get("customer")
    customer = get_object_or_404(Customer, pk=customer_id) if customer_id else None
    order_form = FORM_MAP[business_type](_entry_post_data(request.POST, business_type) if request.method == "POST" else None, customer=customer)
    completion_form = CompletionMetadataForm(request.POST or None, request.FILES or None)
    duplicate_review = _duplicate_review_valid(request, business_type) if request.method == "POST" else False
    duplicate_token = request.POST.get("duplicate_review_token", "") if duplicate_review else ""
    duplicate_candidates = []
    if request.method == "POST" and order_form.is_valid() and completion_form.is_valid():
        order_form.cleaned_data["confirm_duplicate"] = bool(order_form.cleaned_data["confirm_duplicate"] and duplicate_review)
        items = order_form.cleaned_data.get("entry_items")
        if business_type == BusinessType.EXPRESS and items and any(item["size_class"] == SizeClass.UNKNOWN for item in items):
            order_form.add_error("entry_items", "补录已完成快递必须逐件选择实际大小")
        elif business_type in {BusinessType.EXPRESS, BusinessType.ERRAND} and order_form.cleaned_data.get("size_class") == SizeClass.UNKNOWN:
            order_form.add_error("size_class", "补录已完成任务必须选择实际物品大小")
        elif business_type in {BusinessType.TAKEOUT, BusinessType.KFC, BusinessType.GROCERY} and order_form.cleaned_data.get("requires_upstairs") and not (
            (order_form.cleaned_data.get("upstairs_small_medium_count") or 0)
            + (order_form.cleaned_data.get("upstairs_large_oversize_count") or 0)
        ):
            order_form.add_error("upstairs_small_medium_count", "直接完成／历史补录没有后续配送员核对步骤，请填写实际件数")
        else:
            metadata = completion_form.cleaned_data.copy()
            try:
                data = order_form.service_kwargs()
                items = order_form.cleaned_data.get("entry_items")
                if business_type == BusinessType.TAKEOUT and items:
                    data["identifiers"] = items
                elif business_type == BusinessType.KFC and items:
                    data["pickup_codes"] = items
                elif business_type == BusinessType.EXPRESS and items:
                    shared = data.copy()
                    for key in ("pickup_area", "outside_pickup_location", "pickup_identifier", "size_class", "pickup_identifier_type"):
                        shared.pop(key, None)
                    data = [{**shared, **item, "pickup_identifier_type": "OTHER"} for item in items]
                order = create_completed_order(
                    actor=request.user,
                    business_type=business_type,
                    order_data=data,
                    **metadata,
                )
            except PossibleDuplicateOrder as exc:
                duplicate_candidates = exc.orders
                duplicate_token = _duplicate_review_token(request, business_type)
                order_form.add_error(
                    "confirm_duplicate",
                    f"发现 {len(exc.orders)} 条疑似重复订单；核对后可勾选确认继续。",
                )
            except (ValidationError, PermissionError, ValueError) as exc:
                completion_form.add_error(None, exc)
            else:
                first_order = order[0] if isinstance(order, list) else order
                messages.success(request, f"订单 {first_order.fixed_id} 已按实际完成事实录入" + (f"，共 {len(order)} 张" if isinstance(order, list) else ""))
                return redirect(f"{reverse('orders:detail', args=[first_order.pk])}?from_quick=1")
    return render(
        request,
        "orders/quick_complete.html",
        {
            "business_type": business_type,
            "express_areas": [("NORTH", "北区"), ("SOUTH", "南区"), ("OUTSIDE", "校外")],
            "is_create": True,
            "business_label": BusinessType(business_type).label,
            "selected_customer": customer,
            "selected_customer_id": customer.pk if customer else None,
            "picker_buildings": Building.objects.filter(is_active=True),
            "order_form": order_form,
            "item_form": order_form,
            "order_sections": _order_sections(order_form),
            "duplicate_token": duplicate_token,
            "duplicate_candidates": duplicate_candidates,
            "completion_form": completion_form,
        },
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
    form = ExpressOrderForm(
        _entry_post_data(request.POST, BusinessType.EXPRESS) if request.method == "POST" else None,
        proxy_recipient=recipient,
    )
    duplicate_review = _duplicate_review_valid(request, BusinessType.EXPRESS) if request.method == "POST" else False
    duplicate_token = request.POST.get("duplicate_review_token", "") if duplicate_review else ""
    duplicate_candidates = []
    if request.method == "POST" and form.is_valid():
        form.cleaned_data["confirm_duplicate"] = bool(form.cleaned_data["confirm_duplicate"] and duplicate_review)
        try:
            data = form.service_kwargs()
            items = form.cleaned_data.get("entry_items")
            order = (
                create_express_orders(actor=request.user, common_data=data, items=items)[0]
                if items else create_express_order(actor=request.user, **data)
            )
        except PossibleDuplicateOrder as exc:
            duplicate_candidates = exc.orders
            duplicate_token = _duplicate_review_token(request, BusinessType.EXPRESS)
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
            "item_form": form,
            "order_sections": _order_sections(form),
            "duplicate_token": duplicate_token,
            "duplicate_candidates": duplicate_candidates,
            "business_type": BusinessType.EXPRESS,
            "express_areas": [("NORTH", "北区"), ("SOUTH", "南区"), ("OUTSIDE", "校外")],
            "business_label": BusinessType.EXPRESS.label,
            "proxy_recipient": recipient,
            "is_create": True,
        },
    )


@recorder_or_admin_required
def order_history(request):
    query = request.GET.get("q", "").strip()
    business_type = request.GET.get("business_type", "")
    delivery_status = request.GET.get("delivery_status", "")
    destination = request.GET.get("destination", "")
    if business_type not in BusinessType.values:
        business_type = ""
    if delivery_status not in DeliveryStatus.values:
        delivery_status = ""
    if destination not in {"SOUTH", "NORTH", "OUTSIDE"}:
        destination = ""
    page = Paginator(
        search_orders(
            query,
            business_type=business_type,
            delivery_status=delivery_status,
            destination=destination,
        ),
        50,
    ).get_page(request.GET.get("page"))
    from apps.orders.selectors.orders import attach_latest_receipts

    page.object_list = attach_latest_receipts(page.object_list)
    filters = request.GET.copy()
    filters.pop("page", None)
    return render(
        request,
        "orders/history.html",
        {
            "page": page,
            "query": query,
            "business_type": business_type,
            "delivery_status": delivery_status,
            "destination": destination,
            "business_choices": BusinessType.choices,
            "status_choices": DeliveryStatus.choices,
            "filter_query": filters.urlencode(),
        },
    )


@recorder_or_admin_required
def order_show(request, order_id):
    try:
        order = order_detail(order_id)
    except Order.DoesNotExist:
        order = get_object_or_404(search_orders(), pk=order_id)
    return render(request, "orders/detail.html", {
        "order": order,
        "from_quick": request.GET.get("from_quick") == "1" and order.entry_mode in {
            EntryMode.DIRECT_COMPLETE, EntryMode.HISTORICAL_BACKFILL,
        },
    })


@recorder_or_admin_required
def order_receipt_evidence(request, order_id):
    order = get_object_or_404(Order, pk=order_id, soft_deleted_at__isnull=True)
    from apps.settlements.services.receipts import _receipt_photo_state

    available_evidence, _ = _receipt_photo_state(Order.objects.filter(pk=order.pk))
    return render(request, "includes/receipt_evidence.html", {"available_evidence": available_evidence})


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
    if order.business_type == BusinessType.TAKEOUT:
        initial["entry_items"] = json.dumps(list(detail.items.values_list("identifier", flat=True)) or [detail.identifier], ensure_ascii=False)
    elif order.business_type == BusinessType.KFC:
        initial["entry_items"] = json.dumps(list(detail.items.values_list("pickup_code", flat=True)) or [detail.pickup_code], ensure_ascii=False)
    return initial, detail


@recorder_or_admin_required
def order_edit(request, order_id):
    order = order_detail(order_id)
    if order.delivery_status != DeliveryStatus.NEW:
        messages.error(request, "只有待接单订单可以修改")
        return redirect("orders:detail", order_id=order.pk)
    initial, detail = _edit_initial(order)
    form = FORM_MAP[order.business_type](
        _entry_post_data(request.POST, order.business_type) if request.method == "POST" else None,
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
                    pickup_items=data.get("entry_items") if order.business_type in {BusinessType.TAKEOUT, BusinessType.KFC} else None,
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
        {
            "form": form,
            "item_form": form,
            "order_sections": _order_sections(form),
            "business_type": order.business_type,
            "business_label": order.get_business_type_display(),
            "order": order,
            "is_create": False,
        },
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
