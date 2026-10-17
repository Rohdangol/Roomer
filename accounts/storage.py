from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage


class PrivateDocumentStorage(FileSystemStorage):
    def __init__(self):
        # Identity documents must never be served through public media/static URLs.
        super().__init__(location=settings.BASE_DIR / "private_identity")

    def url(self, name):
        raise ValueError("Identity documents require an authorized download.")


def verification_document_path(instance, filename):
    return f"{instance.user_id}/{uuid4().hex}{Path(filename).suffix.lower()}"


def validate_identity_document(document):
    if document.size > 5 * 1024 * 1024:
        raise ValidationError("The document must be 5 MB or smaller.")
    extension = Path(document.name).suffix.lower()
    signatures = {".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".png": b"\x89PNG\r\n\x1a\n", ".pdf": b"%PDF-"}
    signature = signatures.get(extension)
    header = document.read(8)
    document.seek(0)
    if signature is None or not header.startswith(signature):
        raise ValidationError("Upload a JPG, PNG, or PDF document with a matching file format.")


def validate_tenant_identity_document(document):
    from listings.storage import validate_photo
    if not document.name.lower().endswith((".jpg", ".jpeg", ".png")):
        raise ValidationError("Upload a JPEG or PNG image, up to 5 MB.")
    validate_photo(document)
