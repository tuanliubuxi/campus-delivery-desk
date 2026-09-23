"""Local-file metadata and delivery evidence relationships."""

from django.db import models


class MediaVariant(models.TextChoices):
    ORIGINAL_COMPRESSED = "ORIGINAL_COMPRESSED", "压缩原图"
    THUMBNAIL = "THUMBNAIL", "缩略图"
    ANNOTATED = "ANNOTATED", "标注派生图"
    GENERATED_RECEIPT = "GENERATED_RECEIPT", "生成凭证"


class EvidenceRole(models.TextChoices):
    NEAR = "NEAR", "近景"
    FAR = "FAR", "远景"
    OTHER = "OTHER", "其他"


class MediaFile(models.Model):
    """Metadata remains after retention cleanup removes the physical file."""

    storage_key = models.CharField(max_length=255, unique=True)
    mime_type = models.CharField(max_length=80)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    variant_type = models.CharField(max_length=24, choices=MediaVariant.choices)
    parent_media = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="derived_media",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    delete_reason = models.CharField(max_length=255, blank=True)
    protected_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class DeliveryEvidence(models.Model):
    drop = models.ForeignKey(
        "dispatch.DeliveryDrop",
        on_delete=models.PROTECT,
        related_name="evidence",
    )
    order = models.ForeignKey(
        "orders.Order",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="delivery_evidence",
    )
    media = models.ForeignKey(
        MediaFile,
        on_delete=models.PROTECT,
        related_name="delivery_evidence",
    )
    role = models.CharField(max_length=12, choices=EvidenceRole.choices)
    annotated_media = models.ForeignKey(
        MediaFile,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="annotation_evidence",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["drop", "media"],
                name="mediafiles_unique_drop_media_evidence",
            )
        ]
