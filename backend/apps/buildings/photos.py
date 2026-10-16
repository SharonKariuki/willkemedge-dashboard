"""Building cover photos — checked, stored in the database, served back.

Only JPEG, PNG and WebP are accepted, and the type is decided from the file's
own first bytes, never from the name or the Content-Type the browser sent: a
renamed script must not be stored and later served back as an "image".
"""
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Building

# The browser resizes before upload, so a real photo arrives well under this.
MAX_PHOTO_BYTES = 3 * 1024 * 1024


def sniff_image_type(data: bytes) -> str | None:
    """The image MIME type named by the file's signature, or None."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def set_photo(building: Building, upload) -> Building:
    """Store ``upload`` as the building's photo, or raise ValidationError."""
    if upload.size > MAX_PHOTO_BYTES:
        raise ValidationError(
            f"The photo is too large ({upload.size // 1024} KB). The limit is "
            f"{MAX_PHOTO_BYTES // (1024 * 1024)} MB."
        )
    data = upload.read()
    content_type = sniff_image_type(data)
    if content_type is None:
        raise ValidationError("The photo must be a JPEG, PNG or WebP image.")
    building.photo = data
    building.photo_content_type = content_type
    building.photo_updated_at = timezone.now()
    building.save(update_fields=["photo", "photo_content_type", "photo_updated_at", "updated_at"])
    return building


def clear_photo(building: Building) -> Building:
    """Remove the photo; the card falls back to the placeholder."""
    building.photo = None
    building.photo_content_type = ""
    building.photo_updated_at = timezone.now()
    building.save(update_fields=["photo", "photo_content_type", "photo_updated_at", "updated_at"])
    return building
