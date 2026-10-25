from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class RentalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="rental_requests")
    listing = models.ForeignKey("listings.RoomListing", on_delete=models.PROTECT, related_name="rental_requests")
    listing_revision = models.ForeignKey("listings.ListingRevision", on_delete=models.PROTECT, related_name="rental_requests")
    preferred_move_in = models.DateField()
    total_occupancy = models.PositiveSmallIntegerField()
    message = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-requested_at", "-pk")
        constraints = [
            models.UniqueConstraint(fields=["tenant", "listing"], condition=Q(status__in=["pending", "accepted"]), name="request_one_open_application"),
            models.CheckConstraint(condition=Q(total_occupancy__gte=1), name="request_positive_occupancy"),
            models.CheckConstraint(condition=Q(status__in=["pending", "accepted", "rejected", "cancelled"]), name="request_valid_status"),
            models.CheckConstraint(condition=Q(status="pending", responded_at__isnull=True) | Q(status__in=["accepted", "rejected", "cancelled"], responded_at__isnull=False), name="request_response_consistent"),
            models.CheckConstraint(condition=~Q(message=""), name="request_message_required"),
        ]
        indexes = [models.Index(fields=["listing", "status", "requested_at"]), models.Index(fields=["tenant", "status", "requested_at"])]

    def clean(self):
        self.message = self.message.strip()
        if not self.message:
            raise ValidationError({"message": "Enter a message for the Owner."})
        if self.tenant_id and (self.tenant.role != "tenant" or self.tenant.is_staff):
            raise ValidationError("The applicant must be a Tenant.")
        if self.listing_revision_id and (self.listing_revision.listing_id != self.listing_id or self.listing_revision.approval_status != "approved"):
            raise ValidationError("The requested revision must be approved and belong to this listing.")

    def __str__(self):
        return f"Request #{self.pk}"


class RentalAgreement(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Legacy pending"
        DRAFT = "draft", "Draft"
        AWAITING_TENANT = "awaiting_tenant", "Awaiting Tenant"
        CHANGES_REQUESTED = "changes_requested", "Changes Requested"
        PENDING_ADMIN = "pending_admin", "Pending Admin Approval"
        SCHEDULED = "scheduled", "Scheduled"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"

    rental_request = models.OneToOneField(RentalRequest, on_delete=models.PROTECT, related_name="agreement")
    listing = models.ForeignKey("listings.RoomListing", on_delete=models.PROTECT, related_name="rental_agreements")
    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tenant_agreements")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owner_agreements")
    current_terms = models.ForeignKey("AgreementTerms", on_delete=models.PROTECT, null=True, blank=True, related_name="current_for")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    workflow_version = models.PositiveSmallIntegerField(default=2)
    release_status = models.CharField(max_length=16, default="inactive", choices=[("available", "Available"), ("inactive", "Inactive")])
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="completed_agreements")

    class Meta:
        permissions = [("approve_rentalagreement", "Can approve or return rental agreements")]
        ordering = ("-created_at", "-pk")
        constraints = [
            # New workflows reserve from acceptance; legacy pending records are not converted.
            models.UniqueConstraint(fields=["listing"], condition=Q(workflow_version=2, status__in=["draft", "awaiting_tenant", "changes_requested", "pending_admin", "scheduled", "active"]) | Q(workflow_version=1, status__in=["scheduled", "active"]), name="agreement_one_binding_per_listing"),
            models.CheckConstraint(condition=Q(status__in=["pending", "draft", "awaiting_tenant", "changes_requested", "pending_admin", "scheduled", "active", "completed"]), name="agreement_valid_status"),
            models.CheckConstraint(condition=Q(workflow_version__in=[1, 2]), name="agreement_valid_workflow"),
            models.CheckConstraint(condition=Q(status="completed", completed_at__isnull=False) & (Q(workflow_version=2) | Q(completed_by__isnull=False)) | (~Q(status="completed") & Q(completed_at__isnull=True, completed_by__isnull=True)), name="agreement_completion_consistent"),
            models.CheckConstraint(condition=(Q(status="active", activated_at__isnull=False) | Q(status="completed") | (~Q(status__in=["active", "completed"]) & Q(activated_at__isnull=True))), name="agreement_activation_consistent"),
        ]
        indexes = [models.Index(fields=["owner", "status"]), models.Index(fields=["tenant", "status"])]

    def clean(self):
        if self.rental_request_id:
            application = self.rental_request
            if application.status != "accepted" or (self.listing_id, self.tenant_id, self.owner_id) != (application.listing_id, application.tenant_id, application.listing.owner_id):
                raise ValidationError("Agreement parties must match an accepted request.")
        if self.current_terms_id and self.current_terms.agreement_id != self.pk:
            raise ValidationError("Terms must belong to this agreement.")

    def __str__(self):
        return f"Agreement #{self.pk}"


class AgreementTerms(models.Model):
    agreement = models.ForeignKey(RentalAgreement, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    listing_revision = models.ForeignKey("listings.ListingRevision", on_delete=models.PROTECT)
    monthly_rent = models.DecimalField(max_digits=12, decimal_places=2)
    security_deposit = models.DecimalField(max_digits=12, decimal_places=2)
    payment_due_day = models.PositiveSmallIntegerField(null=True, blank=True)
    total_occupancy = models.PositiveSmallIntegerField()
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    additional_terms = models.TextField(blank=True)
    listing_snapshot = models.JSONField()
    tenant_snapshot = models.JSONField()
    owner_snapshot = models.JSONField()
    prepared_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    tenant_accepted_at = models.DateTimeField(null=True, blank=True)
    owner_accepted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="approved_agreement_versions")

    class Meta:
        ordering = ("version",)
        constraints = [
            models.UniqueConstraint(fields=["agreement", "version"], name="agreement_terms_version_unique"),
            models.CheckConstraint(condition=Q(version__gte=1), name="agreement_terms_positive_version"),
            models.CheckConstraint(condition=Q(monthly_rent__gt=0, security_deposit__gte=0), name="agreement_valid_amounts"),
            models.CheckConstraint(condition=Q(payment_due_day__gte=1, payment_due_day__lte=28), name="agreement_valid_due_day"),
            models.CheckConstraint(condition=Q(total_occupancy__gte=1), name="agreement_positive_occupancy"),
            models.CheckConstraint(condition=Q(end_date__isnull=True, sent_at__isnull=True) | Q(end_date__gt=models.F("start_date")), name="agreement_valid_dates"),
            models.CheckConstraint(condition=Q(tenant_accepted_at__isnull=True) | Q(sent_at__isnull=False), name="agreement_confirmation_after_send"),
            models.CheckConstraint(condition=Q(owner_accepted_at__isnull=True) | Q(sent_at__isnull=False), name="agreement_owner_consent_after_send"),
            models.CheckConstraint(condition=Q(sent_at__isnull=True) | Q(payment_due_day__isnull=False, end_date__isnull=False) & ~Q(additional_terms=""), name="agreement_sent_terms_complete"),
            models.CheckConstraint(condition=Q(approved_at__isnull=True, approved_by__isnull=True) | Q(approved_at__isnull=False, approved_by__isnull=False, owner_accepted_at__isnull=False, tenant_accepted_at__isnull=False, sent_at__isnull=False), name="agreement_approval_requires_consent"),
        ]

    def clean(self):
        self.additional_terms = self.additional_terms.strip()
        if self.sent_at and not self.additional_terms:
            raise ValidationError({"additional_terms": "Enter the agreed terms before sending."})
        if self.listing_revision_id and self.agreement_id and (
            self.listing_revision.listing_id != self.agreement.listing_id or self.listing_revision.approval_status != "approved"):
            raise ValidationError("Agreement content must come from an approved revision of this listing.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Agreement versions are immutable; prepare a new version through the workflow.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Agreement #{self.agreement_id} version {self.version}"


class AgreementReview(models.Model):
    class Decision(models.TextChoices):
        TENANT_CHANGES = "tenant_changes", "Tenant requested changes"
        ADMIN_RETURN = "admin_return", "Admin returned for revision"
        ADMIN_APPROVE = "admin_approve", "Admin approved"

    terms = models.ForeignKey(AgreementTerms, on_delete=models.PROTECT, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [models.CheckConstraint(condition=Q(decision="admin_approve", reason="") | Q(decision__in=["tenant_changes", "admin_return"]) & ~Q(reason=""), name="agreement_review_reason_required")]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Agreement reviews are immutable history.")
        super().save(*args, **kwargs)
