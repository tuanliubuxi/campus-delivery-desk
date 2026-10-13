"""Administrator views for inspecting and changing configuration."""

from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.common.permissions import admin_required
from apps.config_center.forms import (
    BuildingForm,
    BusinessTypeConfigForm,
    SiteConfigurationForm,
)
from apps.config_center.models import (
    Building,
    BusinessTypeConfig,
    SiteConfiguration,
)
from apps.config_center.selectors import configuration_center_data
from apps.config_center.services import (
    save_building,
    save_business_config,
    save_site_configuration,
)


@admin_required
def config_index(request):
    context = configuration_center_data()
    context["daily_backup_time"] = (
        f"{settings.DAILY_BACKUP_HOUR:02d}:{settings.DAILY_BACKUP_MINUTE:02d}"
    )
    context["buildings"] = Building.objects.all()
    for item in context["business_configs"]:
        item.edit_form = BusinessTypeConfigForm(instance=item)
    return render(request, "config_center/index.html", context)


@require_POST
@admin_required
def business_config_toggle(request, config_id):
    config = get_object_or_404(BusinessTypeConfig, pk=config_id)
    save_business_config(
        actor=request.user,
        config=config,
        enabled=request.POST.get("enabled") == "on",
    )
    messages.success(request, f"{config.display_name}状态已更新")
    return redirect("config_center:index")


@admin_required
def site_config_edit(request):
    config = SiteConfiguration.load()
    form = SiteConfigurationForm(request.POST or None, instance=config)
    for field_name, short_label in {"express_small_price": "小件", "express_medium_price": "中件", "express_large_price": "大件", "express_oversize_price": "超大件"}.items():
        form.fields[field_name].label = short_label
    if request.method == "POST" and form.is_valid():
        save_site_configuration(actor=request.user, config=config, **form.cleaned_data)
        messages.success(request, "系统价格与规则配置已保存")
        return redirect("config_center:index")
    groups = [
        ("快递大小基础费与目的地附加费", "express", ["express_small_price", "express_medium_price", "express_large_price", "express_oversize_price", "outside_pickup_fee", "campus_to_outside_fee"]),
        ("上楼与行李", "upstairs", ["upstairs_small_medium_rate", "upstairs_large_oversize_rate", "outside_luggage_base_price"]),
        ("天气与优惠", "discount", ["weather_fee", "multi_item_discount_enabled", "multi_item_threshold", "multi_item_discount"]),
        ("薪资与凭证", "finance", ["default_wage_rate", "receipt_brand_name", "image_quality"]),
        ("系统运行", "system", ["default_theme", "kfc_open_weekday", "heartbeat_interval_seconds", "lease_stale_seconds", "media_retention_days"]),
    ]
    return render(request, "config_center/form.html", {
        "form": form, "title": "系统规则配置",
        "field_groups": [(title, color, [form[name] for name in names]) for title, color, names in groups],
    })


@admin_required
def business_config_edit(request, config_id):
    config = get_object_or_404(BusinessTypeConfig, pk=config_id)
    form = BusinessTypeConfigForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        save_business_config(actor=request.user, config=config, **form.cleaned_data)
        messages.success(request, "业务配置已保存")
        return redirect("config_center:index")
    return render(
        request,
        "config_center/form.html",
        {"form": form, "title": f"编辑业务：{config.display_name}"},
    )


@admin_required
def building_edit(request, building_id=None):
    building = get_object_or_404(Building, pk=building_id) if building_id else None
    form = BuildingForm(request.POST or None, instance=building)
    if request.method == "POST" and form.is_valid():
        save_building(actor=request.user, building=building, **form.cleaned_data)
        messages.success(request, "楼栋配置已保存")
        return redirect("config_center:index")
    return render(request, "config_center/form.html", {"form": form, "title": "楼栋配置"})
