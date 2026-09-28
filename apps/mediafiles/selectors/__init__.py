"""Media retention query surface."""

from .retention import is_media_protected, media_delete_after, protected_media_ids

__all__ = ["is_media_protected", "media_delete_after", "protected_media_ids"]
