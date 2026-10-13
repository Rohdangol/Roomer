from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from django.db.models.functions import Lower

from .profile_storage import ProfilePictureStorage, profile_picture_path, validate_profile_picture
from .storage import validate_tenant_identity_document, PrivateDocumentStorage, validate_identity_document, verification_document_path


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
    email_verified_at = models.DateTimeField(null=True, blank=True)
    verified_email = models.EmailField(blank=True)
    profile_picture = models.ImageField(storage=ProfilePictureStorage(), upload_to=profile_picture_path, validators=[validate_profile_picture], blank=True)

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


class EmailVerificationDelivery(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    nonce_digest = models.CharField(max_length=64)
    sent_at = models.DateTimeField()
    window_started_at = models.DateTimeField()
    window_count = models.PositiveSmallIntegerField(default=0)


class TenantIdentityAttempt(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tenant_identity_attempts")
    document_type = models.CharField(max_length=20, choices=OwnerVerification.DocumentType.choices)
    document_number = models.CharField(max_length=100)
    issued_date = models.DateField()
    front_document = models.FileField(storage=PrivateDocumentStorage(), upload_to=verification_document_path, validators=[validate_tenant_identity_document])
    back_document = models.FileField(storage=PrivateDocumentStorage(), upload_to=verification_document_path, validators=[validate_tenant_identity_document])
    status = models.CharField(max_length=20, choices=OwnerVerification.Status.choices, default="pending")
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="tenant_identity_reviews")
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("-submitted_at", "-pk")
        constraints = [models.UniqueConstraint(fields=["user"], condition=models.Q(status__in=["pending", "approved"]), name="tenant_identity_one_open"), models.CheckConstraint(condition=models.Q(status__in=["pending", "approved", "rejected"]), name="tenant_identity_status")]
        indexes = [models.Index(fields=["user", "submitted_at"]), models.Index(fields=["status", "submitted_at"])]

    def clean(self):
        from django.core.exceptions import ValidationError
        from django.utils import timezone
        from zoneinfo import ZoneInfo
        self.document_number = self.document_number.strip()
        if not self.document_number:
            raise ValidationError({"document_number": "Enter a document number."})
        if self.issued_date and self.issued_date > timezone.localdate(timezone=ZoneInfo("Asia/Kathmandu")):
            raise ValidationError({"issued_date": "Enter a past or current AD date."})
        if self.user.role != "tenant":
            raise ValidationError("This submission must belong to a tenant.")

    def save(self, *args, **kwargs):
        if self.pk:
            from django.core.exceptions import ValidationError
            raise ValidationError("Submitted identity attempts are immutable; use review services.")
        super().save(*args, **kwargs)


class TenantIdentityReview(models.Model):
    attempt = models.ForeignKey(TenantIdentityAttempt, on_delete=models.PROTECT, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=20)
    rejection_reason = models.TextField(blank=True)
    outcome = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)
