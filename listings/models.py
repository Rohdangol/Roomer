from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from .choices import Furnishing, RoomType
from .storage import ListingPhotoStorage, photo_path, validate_photo


class Amenity(models.Model):
    name = models.CharField(max_length=80)

    class Meta:
        ordering = ("name",)
        constraints = [models.UniqueConstraint(Lower("name"), name="amenity_name_ci_unique")]

    def clean(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "Enter an amenity name."})

    def __str__(self):
        return self.name


class RoomListing(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        INACTIVE = "inactive", "Inactive"
        OCCUPIED = "occupied", "Occupied"

    class ArchiveSource(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="room_listings")
    published_revision = models.ForeignKey("ListingRevision", on_delete=models.PROTECT, null=True, blank=True, related_name="published_for_listings")
    listing_status = models.CharField(max_length=16, choices=Status.choices, default=Status.INACTIVE)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="archived_listings")
    archive_source = models.CharField(max_length=16, choices=ArchiveSource.choices, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(listing_status__in=["available", "inactive", "occupied"]), name="listing_valid_status"),
            models.CheckConstraint(condition=Q(archived_at__isnull=True, archived_by__isnull=True, archive_source="") | Q(archived_at__isnull=False, archived_by__isnull=False, archive_source__in=["owner", "admin"]), name="listing_archive_consistent"),
        ]
        indexes = [models.Index(fields=["listing_status", "archived_at"]), models.Index(fields=["owner", "listing_status"]), models.Index(fields=["published_at"])]

    def clean(self):
        if self.owner_id and self.owner.role != "owner":
            raise ValidationError({"owner": "The listing must belong to an owner."})
        if self.published_revision_id and (self.published_revision.listing_id != self.pk or self.published_revision.approval_status != "approved"):
            raise ValidationError({"published_revision": "Choose an approved revision of this listing."})

    def __str__(self):
        return f"Listing #{self.pk}"


class ListingRevision(models.Model):
    class Approval(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    listing = models.ForeignKey(RoomListing, on_delete=models.PROTECT, related_name="revisions")
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    description = models.TextField()
    city = models.CharField(max_length=100)
    locality = models.CharField(max_length=100)
    address = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    room_type = models.CharField(max_length=16, choices=RoomType.choices)
    furnishing = models.CharField(max_length=16, choices=Furnishing.choices)
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=2)
    security_deposit = models.DecimalField(max_digits=12, decimal_places=2)
    available_from = models.DateField()
    maximum_occupants = models.PositiveSmallIntegerField()
    floor = models.CharField(max_length=50, blank=True)
    bathroom_details = models.CharField(max_length=255, blank=True)
    cooking_allowed = models.BooleanField()
    visitors_allowed = models.BooleanField()
    smoking_allowed = models.BooleanField()
    pets_allowed = models.BooleanField()
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    additional_rules = models.TextField(blank=True)
    approval_status = models.CharField(max_length=16, choices=Approval.choices, default=Approval.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_listing_revisions")
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("listing_id", "version")
        constraints = [
            models.UniqueConstraint(fields=["listing", "version"], name="revision_version_unique"),
            models.UniqueConstraint(fields=["listing"], condition=Q(approval_status="draft"), name="revision_one_draft"),
            models.UniqueConstraint(fields=["listing"], condition=Q(approval_status="pending"), name="revision_one_pending"),
            models.CheckConstraint(condition=Q(approval_status__in=["draft", "pending", "approved", "rejected"]), name="revision_valid_status"),
            models.CheckConstraint(condition=Q(version__gte=1), name="revision_positive_version"),
            models.CheckConstraint(condition=Q(monthly_rent__gt=0), name="revision_positive_rent"),
            models.CheckConstraint(condition=Q(security_deposit__gte=0), name="revision_nonnegative_deposit"),
            models.CheckConstraint(condition=Q(maximum_occupants__gte=1), name="revision_positive_capacity"),
            models.CheckConstraint(condition=Q(latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180), name="revision_valid_coordinates"),
            models.CheckConstraint(condition=Q(room_type__in=RoomType.values, furnishing__in=Furnishing.values), name="revision_valid_choices"),
            models.CheckConstraint(condition=Q(quiet_hours_start__isnull=True, quiet_hours_end__isnull=True) | Q(quiet_hours_start__isnull=False, quiet_hours_end__isnull=False), name="revision_quiet_hours_pair"),
            models.CheckConstraint(condition=Q(approval_status="draft", submitted_at__isnull=True, reviewed_at__isnull=True, reviewed_by__isnull=True, rejection_reason="") | Q(approval_status="pending", submitted_at__isnull=False, reviewed_at__isnull=True, reviewed_by__isnull=True, rejection_reason="") | Q(approval_status="approved", submitted_at__isnull=False, reviewed_at__isnull=False, reviewed_by__isnull=False, rejection_reason="") | (Q(approval_status="rejected", submitted_at__isnull=False, reviewed_at__isnull=False, reviewed_by__isnull=False) & ~Q(rejection_reason="")), name="revision_review_consistent"),
        ]
        indexes = [models.Index(fields=["listing", "approval_status"]), models.Index(fields=["approval_status", "submitted_at"])]

    def clean(self):
        for name in ("title", "description", "city", "locality", "address"):
            value = getattr(self, name).strip()
            setattr(self, name, value)
            if not value:
                raise ValidationError({name: "This field is required."})

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(approval_status="draft").exists():
            raise ValidationError("Submitted revisions are immutable; use workflow services.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.approval_status != "draft":
            raise ValidationError("Submitted revision history cannot be deleted.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"Listing #{self.listing_id} v{self.version} — {self.title}"


class ListingAmenity(models.Model):
    revision = models.ForeignKey(ListingRevision, on_delete=models.CASCADE, related_name="amenity_links")
    amenity = models.ForeignKey(Amenity, on_delete=models.PROTECT, related_name="listing_links")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["revision", "amenity"], name="listing_amenity_unique")]

    def clean(self):
        if self.revision.approval_status != "draft":
            raise ValidationError("Only draft amenities can be changed.")


class RoomImage(models.Model):
    revision = models.ForeignKey(ListingRevision, on_delete=models.CASCADE, related_name="photos")
    image = models.FileField(storage=ListingPhotoStorage(), upload_to=photo_path, validators=[validate_photo])
    position = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("position",)
        constraints = [models.UniqueConstraint(fields=["revision", "position"], name="revision_photo_position_unique"), models.CheckConstraint(condition=Q(position__gte=1, position__lte=10), name="photo_position_range")]

    def clean(self):
        if self.revision.approval_status != "draft":
            raise ValidationError("Only draft photos can be changed.")
        if self.revision.photos.exclude(pk=self.pk).count() >= 10:
            raise ValidationError("A revision can have at most 10 photos.")
