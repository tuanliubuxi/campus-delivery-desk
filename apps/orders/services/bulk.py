"""Atomic multi-parcel entry; each parcel remains its own Order."""

import uuid

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.orders.models import PickupArea, PickupIdentifierType, SizeClass

from .creation import create_express_order


@transaction.atomic
def create_express_orders(*, actor, common_data, items):
    if not items or len(items) > 50:
        raise ValidationError("每次须录入 1 至 50 件快递")
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"第 {index} 条快递信息格式错误")
        identifier = item.get("pickup_identifier")
        outside = item.get("outside_pickup_location", "")
        if (item.get("pickup_area") not in PickupArea.values
                or item.get("size_class") not in SizeClass.values
                or not isinstance(identifier, str) or not identifier.strip()
                or len(identifier) > 255
                or (item.get("pickup_area") == PickupArea.OUTSIDE and
                    (not isinstance(outside, str) or not outside.strip() or len(outside) > 160))):
            raise ValidationError(f"第 {index} 条快递的区域、标识、大小或校外地点无效")
    operation_id = common_data.get("operation_id") or uuid.uuid4()
    orders = []
    for index, item in enumerate(items):
        data = common_data.copy()
        data.update({
            "pickup_area": item["pickup_area"],
            "outside_pickup_location": item.get("outside_pickup_location", "") if item["pickup_area"] == "OUTSIDE" else "",
            "pickup_identifier": item["pickup_identifier"],
            "size_class": item["size_class"],
            "pickup_identifier_type": PickupIdentifierType.OTHER,
            "operation_id": operation_id if index == 0 else uuid.uuid5(uuid.NAMESPACE_URL, f"express-entry:{operation_id}:{index}"),
        })
        orders.append(create_express_order(actor=actor, **data))
    return orders
