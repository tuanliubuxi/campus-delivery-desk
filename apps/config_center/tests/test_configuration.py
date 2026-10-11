"""Acceptance coverage for configuration validation, history, and audit."""

import shutil
import uuid
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.models import User
from apps.common.enums import BusinessType, Theme, UserRole
from apps.config_center.models import Building, BusinessTypeConfig, SiteConfiguration, Zone
from apps.config_center.services import save_building, save_business_config, save_site_configuration
from apps.mediafiles.services import store_delivery_image


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="config-admin",
        password="Strong-pass-123",
        display_name="配置管理员",
        role=UserRole.ADMIN,
    )


@pytest.mark.django_db
def test_v1_default_configuration_is_seeded():
    config = SiteConfiguration.load()
    assert config.express_small_price == Decimal("2.00")
    assert config.express_oversize_price == Decimal("8.00")
    assert config.kfc_open_weekday == 4
    assert config.default_theme == Theme.LIGHT
    assert config.receipt_brand_name == "校驿"
    assert config.image_quality == "STANDARD"
    assert BusinessTypeConfig.objects.count() == 6
    assert Building.objects.filter(zone=Zone.SOUTH).count() == 10
    assert Building.objects.filter(zone=Zone.NORTH).count() == 8


@pytest.mark.django_db
def test_image_quality_changes_stored_resolution(admin_user, settings):
    root = Path(settings.BASE_DIR) / "data" / "tmp" / f"quality-test-{uuid.uuid4().hex}"
    settings.MEDIA_ROOT = root / "media"
    settings.TMP_ROOT = root / "tmp"
    buffer = BytesIO()
    Image.new("RGB", (4000, 1000), "white").save(buffer, format="JPEG")

    def upload():
        return SimpleUploadedFile("label.jpg", buffer.getvalue(), content_type="image/jpeg")

    try:
        standard = store_delivery_image(upload=upload())
        assert standard.width == 1600
        config = SiteConfiguration.load()
        save_site_configuration(
            actor=admin_user, config=config, image_quality="CLEAR", receipt_brand_name="我的团队"
        )
        clear = store_delivery_image(upload=upload())
        assert clear.width == 2400
        config.refresh_from_db()
        assert config.receipt_brand_name == "我的团队"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.django_db
def test_luggage_urgent_cannot_be_enabled(admin_user):
    config = BusinessTypeConfig.objects.get(business_type=BusinessType.LUGGAGE_UPSTAIRS)
    save_business_config(
        actor=admin_user,
        config=config,
        urgent_supported=True,
        urgent_fee=Decimal("99.00"),
    )
    config.refresh_from_db()
    assert config.urgent_supported is False
    assert config.urgent_fee == Decimal("0.00")


@pytest.mark.django_db
def test_only_admin_can_change_configuration(admin_user):
    recorder = User.objects.create_user(
        username="not-admin",
        password="Strong-pass-123",
        display_name="录单员",
        role=UserRole.RECORDER,
    )
    with pytest.raises(PermissionError):
        save_site_configuration(
            actor=recorder,
            config=SiteConfiguration.load(),
            weather_fee=Decimal("3.00"),
        )
    building = Building.objects.first()
    save_building(
        actor=admin_user,
        building=building,
        code=building.code,
        name="新楼栋名",
        zone=building.zone,
        route_order=building.route_order,
        is_active=True,
    )
    building.refresh_from_db()
    assert building.name == "新楼栋名"
