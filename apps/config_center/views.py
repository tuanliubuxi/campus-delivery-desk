"""Administrator views for inspecting and changing configuration."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.common.permissions import admin_required
from apps.config_center.forms import (
    BuildingForm,
    BusinessTypeConfigForm,
    CommissionConfigForm,
    SiteConfigurationForm,
)
from apps.config_center.models import (
    Building,
    BusinessTypeConfig,
    CommissionConfig,
    SiteConfiguration,
)
from apps.config_center.selectors import configuration_center_data
from apps.config_center.services import (
    save_building,
    save_business_config,
    save_commission,
    save_site_configuration,
)


@admin_required
def config_index(request):
    context = configuration_center_data()
    context["buildings"] = Building.objects.all()
    return render(request, "config_center/index.html", context)


@admin_required
def site_config_edit(request):
    config = SiteConfiguration.load()
    form = SiteConfigurationForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        save_site_configuration(actor=request.user, config=config, **form.cleaned_data)
        messages.success(request, "系统价格与规则配置已保存")
        return redirect("config_center:index")
    return render(request, "config_center/form.html", {"form": form, "title": "系统规则配置"})


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


@admin_required
def commission_edit(request, commission_id):
    commission = get_object_or_404(CommissionConfig, pk=commission_id)
    form = CommissionConfigForm(request.POST or None, instance=commission)
    if request.method == "POST" and form.is_valid():
        save_commission(
            actor=request.user,
            commission=commission,
            rate=form.cleaned_data["commission_rate"],
        )
        messages.success(request, "分成比例已保存；未来订单会保存当时快照")
        return redirect("config_center:index")
    return render(request, "config_center/form.html", {"form": form, "title": "编辑分成比例"})
