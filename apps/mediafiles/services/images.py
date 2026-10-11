"""Validate, compress, and atomically persist local image uploads."""

import hashlib
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.mediafiles.models import MediaFile, MediaVariant

IMAGE_PROFILES = {
    "STANDARD": (1600, 85),
    "CLEAR": (2400, 92),
    "EXTRA_CLEAR": (3200, 95),
}


def media_absolute_path(media):
    """Resolve a metadata storage key without accepting caller-controlled paths."""
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / media.storage_key).resolve()
    if root not in path.parents:
        raise ValidationError("媒体文件路径无效")
    return path


def store_delivery_image(*, upload, variant_type=MediaVariant.ORIGINAL_COMPRESSED, parent=None):
    """Decode real image bytes, strip metadata, compress, then atomically publish."""
    if not upload:
        return None
    if variant_type == MediaVariant.GENERATED_RECEIPT:
        # A tall receipt must not be shrunk to a phone-photo limit after rendering.
        max_side, jpeg_quality = None, 90
    else:
        from apps.config_center.models import SiteConfiguration

        max_side, jpeg_quality = IMAGE_PROFILES[SiteConfiguration.load().image_quality]
    try:
        image = Image.open(upload)
        image.verify()
        upload.seek(0)
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image)
        if max_side is not None:
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if image.mode not in {"RGB", "L"}:
            background = Image.new("RGB", image.size, "white")
            if "A" in image.getbands():
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image)
            image = background
        elif image.mode == "L":
            image = image.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError("上传文件不是可识别的图片") from exc

    date_path = timezone.localdate()
    storage_key = f"delivery/{date_path:%Y/%m/%d}/{uuid.uuid4().hex}.jpg"
    final_path = Path(settings.MEDIA_ROOT) / storage_key
    temp_root = Path(settings.TMP_ROOT)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_path = temp_root / f"upload-{uuid.uuid4().hex}.tmp"
    try:
        image.save(temp_path, format="JPEG", quality=jpeg_quality, optimize=True)
        content = temp_path.read_bytes()
        os.replace(temp_path, final_path)
        try:
            return MediaFile.objects.create(
                storage_key=storage_key,
                mime_type="image/jpeg",
                width=image.width,
                height=image.height,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                variant_type=variant_type,
                parent_media=parent,
            )
        except Exception:
            # Do not leave an untracked physical image if metadata persistence fails.
            final_path.unlink(missing_ok=True)
            raise
    finally:
        temp_path.unlink(missing_ok=True)
