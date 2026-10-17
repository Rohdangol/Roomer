from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from listings.storage import validate_photo


class ProfilePictureStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.BASE_DIR / "media" / "profile_pictures")

    def url(self, name):
        # Profile uploads are served only through the signed-in tenant's own endpoint.
        raise ValueError("Profile pictures require authorized access.")


def profile_picture_path(instance, filename):
    return f"{instance.pk}/{uuid4().hex}{Path(filename).suffix.lower()}"


def validate_profile_picture(picture):
    # Use the existing actual-content, size and nonanimation photo validation.
    validate_photo(picture)
