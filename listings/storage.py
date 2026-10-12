from io import BytesIO
from pathlib import Path
from uuid import uuid4
import warnings

from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage


class ListingPhotoStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.BASE_DIR / "media" / "listing_photos")

    def url(self, name):
        # Future delivery views must authorize published photos, never expose drafts.
        raise ValueError("Listing photos require a published-photo delivery endpoint.")


def photo_path(instance, filename):
    return f"{instance.revision_id}/{uuid4().hex}{Path(filename).suffix.lower()}"


def validate_photo(photo):
    if photo.size > 5 * 1024 * 1024:
        raise ValidationError("Each photo must be 5 MB or smaller.")
    expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}.get(Path(photo.name).suffix.lower())
    if expected is None:
        raise ValidationError("Upload a nonanimated JPEG, PNG or WebP photo.")
    try:
        # Decode content twice: verify structure, then load pixels and reject animation.
        photo.seek(0)
        content = photo.read()
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != expected or getattr(image, "n_frames", 1) != 1:
                    raise ValidationError("Photo format must match its extension; animation is not allowed.")
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image.load()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValidationError("Upload a valid, readable image.")
    finally:
        photo.seek(0)
