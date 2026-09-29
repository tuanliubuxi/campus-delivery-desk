"""Phase 8 acceptance tests for exception evidence, retention, and completed entry."""

import io
import shutil
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.common.enums import BusinessType, UserRole
from apps.config_center.models import Building
from apps.customers.models import Customer
from apps.dispatch.models import (
    DeliveryDrop,
    DeliveryDropItem,
    DeliveryTask,
    LocationType,
    TaskType,
)
from apps.exceptions.models import (
    ExceptionCaseAttachment,
    ExceptionEvidenceLink,
    ExceptionStatus,
    ManualHandling,
    ManualHandlingAction,
)
from apps.exceptions.services import (
    create_exception_case,
    perform_manual_handling,
    resolve_exception_case,
    update_exception_blockers,
)
from apps.mediafiles.models import DeliveryEvidence, EvidenceRole, MediaFile, MediaVariant
from apps.mediafiles.selectors import is_media_protected, media_delete_after
from apps.orders.models import (
    DeliveryStatus,
    DestinationType,
    EntryMode,
    RecipientKind,
    TakeoutGate,
)
from apps.orders.services import create_completed_order, create_takeout_order
from apps.settlements.models import (
    ChargeType,
    CourierEarning,
    EarningStatus,
    Settlement,
    SettlementPartyType,
    SettlementStatus,
)
from apps.settlements.services import calculate_wages, record_refund


@pytest.fixture(autouse=True)
def isolated_media(settings):
    root = Path(settings.BASE_DIR) / "data" / "tmp" / f"phase8-{uuid.uuid4().hex}"
    settings.MEDIA_ROOT = root / "media"
    settings.TMP_ROOT = root / "tmp"
    yield
    shutil.rmtree(root, ignore_errors=True)


def image_upload(name="evidence.jpg"):
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "orange").save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


def people_and_customer():
    recorder = User.objects.create_user(username=f"rec-{uuid.uuid4().hex}", role=UserRole.RECORDER)
    admin = User.objects.create_user(username=f"admin-{uuid.uuid4().hex}", role=UserRole.ADMIN)
    courier = User.objects.create_user(username=f"cour-{uuid.uuid4().hex}", role=UserRole.COURIER)
    building = Building.objects.first()
    customer = Customer.objects.create(
        wechat_nickname="Phase8 客户", building=building, created_by=recorder
    )
    return recorder, admin, courier, building, customer


@pytest.mark.django_db
def test_exception_attachments_links_open_protection_and_resolved_grace_period():
    recorder, admin, courier, building, customer = people_and_customer()
    order = create_takeout_order(
        actor=recorder,
        customer=customer,
        pickup_gate=TakeoutGate.SOUTH_GATE,
        identifier="T-1",
        building=building,
        destination_type=DestinationType.CAMPUS_BUILDING,
    )
    drop = DeliveryDrop.objects.create(
        courier=courier,
        recipient_kind=RecipientKind.CUSTOMER,
        customer=customer,
        business_type=BusinessType.TAKEOUT,
        building_snapshot=building.name,
        location_type=LocationType.RACK,
        final_location_text="架子",
        operation_id=uuid.uuid4(),
        delivered_at=timezone.now(),
    )
    DeliveryDropItem.objects.create(drop=drop, order=order)
    linked_media = MediaFile.objects.create(
        storage_key=f"test/{uuid.uuid4().hex}.jpg",
        mime_type="image/jpeg",
        width=10,
        height=10,
        size_bytes=10,
        sha256="a" * 64,
        variant_type=MediaVariant.ORIGINAL_COMPRESSED,
    )
    annotated_media = MediaFile.objects.create(
        storage_key=f"test/{uuid.uuid4().hex}.jpg",
        mime_type="image/jpeg",
        width=10,
        height=10,
        size_bytes=10,
        sha256="b" * 64,
        variant_type=MediaVariant.ANNOTATED,
        parent_media=linked_media,
    )
    evidence = DeliveryEvidence.objects.create(
        drop=drop,
        order=order,
        media=linked_media,
        annotated_media=annotated_media,
        role=EvidenceRole.NEAR,
    )
    operation_id = uuid.uuid4()
    case = create_exception_case(
        actor=recorder,
        order=order,
        drop=drop,
        reason_code="DAMAGED",
        reason_text="外包装破损",
        blocks_settlement=True,
        attachments=[image_upload()],
        delivery_evidence=[evidence],
        operation_id=operation_id,
    )
    assert (
        create_exception_case(
            actor=recorder,
            order=order,
            reason_code="DUPLICATE",
            reason_text="重复提交",
            operation_id=operation_id,
        ).pk
        == case.pk
    )
    attachment = ExceptionCaseAttachment.objects.get(exception_case=case)
    assert ExceptionEvidenceLink.objects.filter(
        exception_case=case, delivery_evidence=evidence
    ).exists()
    assert is_media_protected(attachment.media)
    assert is_media_protected(linked_media)
    assert is_media_protected(annotated_media)

    update_exception_blockers(
        case=case,
        actor=admin,
        blocks_consolidation=True,
        blocks_settlement=False,
        reason="已核实仅影响归拢",
    )
    assert AuditEvent.objects.filter(event_type="EXCEPTION_BLOCKERS_CHANGED").exists()
    resolve_exception_case(case=case, actor=recorder, resolution_text="已重新包装并核对")
    case.refresh_from_db()
    attachment.media.refresh_from_db()
    assert case.status == ExceptionStatus.RESOLVED
    assert not is_media_protected(attachment.media)
    assert media_delete_after(attachment.media, retention_days=30) >= case.resolved_at
    assert attachment.media.protected_until >= case.resolved_at


@pytest.mark.django_db
def test_direct_complete_and_historical_backfill_preserve_real_completion_facts():
    recorder, admin, courier, building, customer = people_and_customer()
    direct = create_completed_order(
        actor=recorder,
        business_type=BusinessType.TAKEOUT,
        order_data={
            "customer": customer,
            "pickup_gate": TakeoutGate.SOUTH_GATE,
            "identifier": "DIRECT-1",
            "building": building,
            "destination_type": DestinationType.CAMPUS_BUILDING,
        },
        actual_courier=courier,
        completed_at=timezone.now(),
        final_location_text="1号架",
        location_type=LocationType.RACK,
        entry_mode=EntryMode.DIRECT_COMPLETE,
        operation_id=uuid.uuid4(),
        near_photo=image_upload("direct.jpg"),
    )
    assert direct.delivery_status == DeliveryStatus.DELIVERED
    assert direct.entry_mode == EntryMode.DIRECT_COMPLETE
    assert not direct.assignments.exists()
    assert direct.delivery_evidence.exists()
    assert (
        CourierEarning.objects.get(order=direct, courier=courier).status
        == EarningStatus.PENDING_PAYMENT
    )

    with pytest.raises(ValidationError, match="补录说明"):
        create_completed_order(
            actor=recorder,
            business_type=BusinessType.KFC,
            order_data={
                "customer": customer,
                "pickup_location": "南门",
                "pickup_code": "H-1",
                "building": building,
                "destination_type": DestinationType.CAMPUS_BUILDING,
                "allow_duplicate": True,
            },
            actual_courier=courier,
            completed_at=timezone.now(),
            final_location_text="宿舍门口",
            location_type=LocationType.HANDOFF,
            entry_mode=EntryMode.HISTORICAL_BACKFILL,
            operation_id=uuid.uuid4(),
        )
    historical = create_completed_order(
        actor=recorder,
        business_type=BusinessType.KFC,
        order_data={
            "customer": customer,
            "pickup_location": "南门",
            "pickup_code": "H-2",
            "building": building,
            "destination_type": DestinationType.CAMPUS_BUILDING,
            "allow_duplicate": True,
        },
        actual_courier=courier,
        completed_at=timezone.now(),
        final_location_text="宿舍门口",
        location_type=LocationType.HANDOFF,
        entry_mode=EntryMode.HISTORICAL_BACKFILL,
        operation_id=uuid.uuid4(),
        entry_note="补录昨日微信订单",
    )
    assert historical.entry_note == "补录昨日微信订单"
    assert not historical.delivery_evidence.exists()
    assert historical.delivery_drop_items.get().drop.delivered_at is not None


@pytest.mark.django_db
def test_refund_can_explicitly_reduce_pool_and_one_courier_wage():
    recorder, admin, courier, building, customer = people_and_customer()
    settlement = Settlement.objects.create(
        business_type=BusinessType.TAKEOUT,
        party_type=SettlementPartyType.CUSTOMER,
        customer=customer,
        status=SettlementStatus.SETTLED,
        amount_due_snapshot=Decimal("10.00"),
        settled_at=timezone.now(),
        settled_by=recorder,
        created_by=recorder,
    )
    adjustment = record_refund(
        settlement=settlement,
        actor=recorder,
        amount="2.00",
        reason="售后退款并扣减对应配送员工资",
        operation_id=uuid.uuid4(),
        impact_wage=True,
        wage_courier=courier,
        wage_amount="1.00",
    )
    assert adjustment.amount == Decimal("-2.00")
    assert adjustment.wage_amount == Decimal("-1.00")
    # Wage periods are local business dates, not the UTC date component of the timestamp.
    business_day = timezone.localdate(settlement.settled_at)
    calculation = calculate_wages(
        period_start=business_day,
        period_end=business_day,
        mode="RATIO",
    )
    assert calculation.available_pool == Decimal("-2.00")
    assert calculation.lines[0].wage_adjustment == Decimal("-1.00")
    assert calculation.lines[0].final_amount == Decimal("-1.00")


@pytest.mark.django_db
def test_manual_handling_is_immutable_and_delegates_financial_actions():
    recorder, admin, courier, building, customer = people_and_customer()
    draft = Settlement.objects.create(
        business_type=BusinessType.TAKEOUT,
        party_type=SettlementPartyType.CUSTOMER,
        customer=customer,
        status=SettlementStatus.DRAFT,
        created_by=recorder,
    )
    surcharge = perform_manual_handling(
        actor=recorder,
        action_type=ManualHandlingAction.ADD_EXTRA_CHARGE,
        reason="额外跑楼服务",
        amount="3.00",
        settlement=draft,
        beneficiary_courier=courier,
        operation_id=uuid.uuid4(),
    )
    assert surcharge.resulting_charge_item.charge_type == ChargeType.MANUAL_SURCHARGE
    assert surcharge.resulting_charge_item.amount == Decimal("3.00")

    waived = perform_manual_handling(
        actor=recorder,
        action_type=ManualHandlingAction.WAIVE_CHARGE,
        reason="客户投诉后全免",
        settlement=draft,
        operation_id=uuid.uuid4(),
    )
    assert waived.resulting_charge_item.charge_type == ChargeType.MANUAL_DISCOUNT
    assert waived.resulting_charge_item.amount == Decimal("-3.00")

    settled = Settlement.objects.create(
        business_type=BusinessType.TAKEOUT,
        party_type=SettlementPartyType.CUSTOMER,
        customer=customer,
        status=SettlementStatus.SETTLED,
        amount_due_snapshot=Decimal("10.00"),
        settled_at=timezone.now(),
        settled_by=recorder,
        created_by=recorder,
    )
    refund_operation = uuid.uuid4()
    refund = perform_manual_handling(
        actor=recorder,
        action_type=ManualHandlingAction.PARTIAL_REFUND,
        reason="售后部分退款",
        amount="2.00",
        settlement=settled,
        operation_id=refund_operation,
    )
    assert refund.resulting_financial_adjustment.amount == Decimal("-2.00")
    assert (
        perform_manual_handling(
            actor=recorder,
            action_type=ManualHandlingAction.PARTIAL_REFUND,
            reason="浏览器重试",
            amount="2.00",
            settlement=settled,
            operation_id=refund_operation,
        ).pk
        == refund.pk
    )

    fully_refunded = Settlement.objects.create(
        business_type=BusinessType.TAKEOUT,
        party_type=SettlementPartyType.CUSTOMER,
        customer=customer,
        status=SettlementStatus.SETTLED,
        amount_due_snapshot=Decimal("5.00"),
        settled_at=timezone.now(),
        settled_by=recorder,
        created_by=recorder,
    )
    full_refund = perform_manual_handling(
        actor=recorder,
        action_type=ManualHandlingAction.FULL_REFUND,
        reason="整单退款",
        settlement=fully_refunded,
        operation_id=uuid.uuid4(),
    )
    assert full_refund.resulting_financial_adjustment.amount == Decimal("-5.00")

    offline = Settlement.objects.create(
        business_type=BusinessType.TAKEOUT,
        party_type=SettlementPartyType.CUSTOMER,
        customer=customer,
        status=SettlementStatus.WAITING_PAYMENT,
        amount_due_snapshot=Decimal("0.00"),
        created_by=recorder,
    )
    perform_manual_handling(
        actor=recorder,
        action_type=ManualHandlingAction.OFFLINE_SETTLEMENT,
        reason="已线下收款",
        settlement=offline,
        operation_id=uuid.uuid4(),
    )
    offline.refresh_from_db()
    assert offline.status == SettlementStatus.SETTLED

    with pytest.raises(TypeError, match="immutable"):
        refund.save()
    with pytest.raises(TypeError, match="immutable"):
        ManualHandling.objects.filter(pk=refund.pk).update(reason="不得覆盖")


@pytest.mark.django_db
def test_manual_handling_records_non_state_machine_actions_and_existing_results():
    assert set(ManualHandlingAction.values) == {
        "ADD_EXTRA_CHARGE",
        "REDUCE_CHARGE",
        "WAIVE_CHARGE",
        "FULL_REFUND",
        "PARTIAL_REFUND",
        "REDELIVERY",
        "POST_PICKUP_CANCEL",
        "CUSTOMER_RESOLVED",
        "OFFLINE_SETTLEMENT",
        "INFO_CORRECTION",
        "OTHER",
    }
    recorder, admin, courier, building, customer = people_and_customer()
    order = create_takeout_order(
        actor=recorder,
        customer=customer,
        pickup_gate=TakeoutGate.SOUTH_GATE,
        identifier="MANUAL-1",
        building=building,
        destination_type=DestinationType.CAMPUS_BUILDING,
    )
    order.delivery_status = DeliveryStatus.PICKED
    order.save(update_fields=["delivery_status"])
    task = DeliveryTask.objects.create(
        task_type=TaskType.SIMPLE,
        business_type=BusinessType.TAKEOUT,
        courier=courier,
        operation_id=uuid.uuid4(),
        accepted_at=timezone.now(),
    )
    case = create_exception_case(
        actor=recorder,
        order=order,
        reason_code="POST_PICKUP_CANCEL",
        reason_text="取件后客户取消",
    )
    handling = perform_manual_handling(
        actor=recorder,
        action_type=ManualHandlingAction.POST_PICKUP_CANCEL,
        reason="实物已取，保留原状态并转异常处理",
        order=order,
        exception_case=case,
        operation_id=uuid.uuid4(),
    )
    order.refresh_from_db()
    assert handling.exception_case == case
    assert order.delivery_status == DeliveryStatus.PICKED

    redelivery = perform_manual_handling(
        actor=recorder,
        action_type=ManualHandlingAction.REDELIVERY,
        reason="已通过配送服务建立重新配送任务",
        order=order,
        delivery_task=task,
        exception_case=case,
        operation_id=uuid.uuid4(),
    )
    assert redelivery.delivery_task == task

    resolved = perform_manual_handling(
        actor=recorder,
        action_type=ManualHandlingAction.CUSTOMER_RESOLVED,
        reason="客户已自行取回",
        order=order,
        exception_case=case,
        operation_id=uuid.uuid4(),
    )
    case.refresh_from_db()
    assert resolved.exception_case == case
    assert case.status == ExceptionStatus.RESOLVED
    assert AuditEvent.objects.filter(
        event_type="MANUAL_HANDLING_RECORDED", entity_id=resolved.pk
    ).exists()
