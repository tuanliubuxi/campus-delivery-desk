"""Date/task evidence choices must remain human-readable and role-scoped."""

import json
import uuid
from pathlib import Path

import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts.models import User
from apps.common.enums import BusinessType, UserRole
from apps.customers.models import Customer
from apps.dispatch.models import DeliveryDrop, LocationType
from apps.exceptions.views import evidence_choices
from apps.mediafiles.models import DeliveryEvidence, EvidenceRole, MediaFile, MediaVariant
from apps.orders.models import RecipientKind


@pytest.mark.django_db
def test_courier_evidence_picker_is_date_scoped_and_hides_other_couriers(settings):
    evidence_root = Path(settings.BASE_DIR) / "data" / "tmp" / f"evidence-picker-{uuid.uuid4().hex}"
    evidence_root.mkdir(parents=True)
    settings.MEDIA_ROOT = evidence_root
    now = timezone.now()
    own = User.objects.create_user(username="evidence-own", role=UserRole.COURIER, display_name="配送甲")
    other = User.objects.create_user(username="evidence-other", role=UserRole.COURIER, display_name="配送乙")
    customer = Customer.objects.create(wechat_nickname="证据客户")
    for index, courier in enumerate((own, other), start=1):
        drop = DeliveryDrop.objects.create(
            courier=courier, recipient_kind=RecipientKind.CUSTOMER,
            customer=customer, business_type=BusinessType.TAKEOUT,
            location_type=LocationType.HANDOFF, final_location_text="东门",
            operation_id=uuid.uuid4(), delivered_at=now,
        )
        media = MediaFile.objects.create(
            storage_key=f"evidence-test-{uuid.uuid4().hex}.jpg", mime_type="image/jpeg",
            width=100, height=100, size_bytes=1, sha256=f"{index:064x}",
            variant_type=MediaVariant.ORIGINAL_COMPRESSED,
        )
        (evidence_root / media.storage_key).write_bytes(b"evidence")
        DeliveryEvidence.objects.create(drop=drop, media=media, role=EvidenceRole.NEAR)
    request = RequestFactory().get(
        "/exceptions/evidence-choices/",
        {"kind": "delivery", "date": timezone.localdate().isoformat()},
    )
    request.user = own
    response = evidence_choices(request)
    assert response.status_code == 200
    data = json.loads(response.content)
    assert len(data["evidence"]) == 1
    assert "证据客户" in data["evidence"][0]["label"]
    assert "配送 #" in data["tasks"][0]["label"]
