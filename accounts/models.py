from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from django.db.models.functions import Lower

from .storage import PrivateDocumentStorage, validate_identity_document, verification_document_path


class UserManager(DjangoUserManager):
    @classmethod
    def normalize_email(cls, email):
        # Treat the entire email address consistently for signup and future login.
        return (email or "").strip().lower()


class User(AbstractUser):
    class Role(models.TextChoices):
        TENANT = "tenant", "Tenant"
        OWNER = "owner", "Owner"

    # A Roomer role describes how a user uses the site; admin permissions stay separate.
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.TENANT)
    full_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(unique=True)

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            # Protect uniqueness even when a database write bypasses save().
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    def save(self, *args, **kwargs):
        self.email = type(self).objects.normalize_email(self.email)
        return super().save(*args, **kwargs)


class OwnerVerification(models.Model):
    class DocumentType(models.TextChoices):
        CITIZENSHIP = "citizenship", "Citizenship"
        NATIONAL_ID = "national_id", "National ID"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owner_verification")
    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    document = models.FileField(
        storage=PrivateDocumentStorage(), upload_to=verification_document_path,
        validators=[validate_identity_document],
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    submitted_at = models.DateTimeField()
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_owner_verifications",
    )
    rejection_reason = models.TextField(blank=True)

    def __str__(self):
        return f"Owner verification #{self.pk} — {self.get_status_display()}"
