"""Transactional configuration mutations with audit snapshots."""

from django.db import transaction
from django.forms.models import model_to_dict

from apps.audit.services import record_event
from apps.common.enums import BusinessType
from apps.config_center.models import (
    Building,
    BusinessTypeConfig,
    CommissionConfig,
    SiteConfiguration,
)


def _require_admin(actor):
    if not actor.is_authenticated or not actor.is_admin:
        raise PermissionError("仅管理员可修改系统配置")


def _json_values(instance):
    return {key: str(value) if value is not None else None for key, value in model_to_dict(instance).items()}


@transaction.atomic
def save_building(*, actor, building=None, **data):
    _require_admin(actor)
    if building and building.pk:
        building = Building.objects.get(pk=building.pk)
    building = building or Building()
    before = _json_values(building) if building.pk else None
    for field, value in data.items():
        setattr(building, field, value)
    building.full_clean()
    building.save()
    record_event(
        actor=actor,
        event_type="BUILDING_SAVED",
        entity=building,
        metadata={"before": before, "after": _json_values(building)},
    )
    return building


@transaction.atomic
def save_business_config(*, actor, config, **data):
    _require_admin(actor)
    config = BusinessTypeConfig.objects.get(pk=config.pk)
    before = _json_values(config)
    for field, value in data.items():
        setattr(config, field, value)
    if config.business_type == BusinessType.LUGGAGE_UPSTAIRS:
        config.urgent_supported = False
        config.urgent_fee = 0
    config.full_clean()
    config.save()
    record_event(
        actor=actor,
        event_type="BUSINESS_CONFIG_CHANGED",
        entity=config,
        metadata={"before": before, "after": _json_values(config)},
    )
    return config


@transaction.atomic
def save_site_configuration(*, actor, config, **data):
    _require_admin(actor)
    config = SiteConfiguration.objects.get(pk=config.pk)
    before = _json_values(config)
    for field, value in data.items():
        setattr(config, field, value)
    config.save()
    record_event(
        actor=actor,
        event_type="SITE_CONFIG_CHANGED",
        entity=config,
        metadata={"before": before, "after": _json_values(config)},
    )
    return config


@transaction.atomic
def save_commission(*, actor, commission, rate):
    _require_admin(actor)
    commission = CommissionConfig.objects.get(pk=commission.pk)
    before = str(commission.commission_rate)
    commission.commission_rate = rate
    commission.full_clean()
    commission.save(update_fields=["commission_rate"])
    record_event(
        actor=actor,
        event_type="COMMISSION_CONFIG_CHANGED",
        entity=commission,
        metadata={"before": before, "after": str(rate)},
    )
    return commission
