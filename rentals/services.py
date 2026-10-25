from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import owner_needs_verification
from listings.models import RoomListing
from listings.services import require_owner
from notifications.services import create_notification
from .models import RentalAgreement, RentalRequest


def require_tenant(actor):
    if not actor.is_authenticated or not actor.is_active or actor.is_staff or actor.role != "tenant":
        raise PermissionDenied("An active Tenant account is required.")


def require_verified_owner(actor, listing=None):
    require_owner(actor, listing)
    if owner_needs_verification(actor):
        raise PermissionDenied("Owner identity approval is required.")


def validate_request_listing(listing, move_in, occupancy):
    revision = listing.published_revision
    if (listing.archived_at or listing.listing_status != "available" or not revision
        or revision.approval_status != "approved" or not listing.owner.is_active
        or listing.owner.is_staff or listing.owner.role != "owner" or owner_needs_verification(listing.owner)):
        raise ValidationError("This listing is no longer available for rental requests.")
    if RentalAgreement.objects.filter(listing=listing).exclude(status__in=["completed", "pending"]).exists():
        raise ValidationError("This listing already has a reserved or active rental agreement.")
    if move_in < max(timezone.localdate(), revision.available_from):
        raise ValidationError("Move-in must be today or later and on or after the listing availability date.")
    if not 1 <= occupancy <= revision.maximum_occupants:
        raise ValidationError("Total occupancy must include you and fit the listing capacity.")


@transaction.atomic
def submit_request(actor, listing_id, *, preferred_move_in, total_occupancy, message):
    require_tenant(actor)
    # All listing decisions lock this row first, serializing applications and availability changes.
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    validate_request_listing(listing, preferred_move_in, total_occupancy)
    if RentalRequest.objects.filter(tenant=actor, listing=listing, status__in=["pending", "accepted"]).exists():
        raise ValidationError("You already have a pending or accepted request for this listing.")
    application = RentalRequest(tenant=actor, listing=listing, listing_revision=listing.published_revision,
        preferred_move_in=preferred_move_in, total_occupancy=total_occupancy, message=message)
    application.full_clean()
    application.save()
    create_notification(listing.owner, "New rental request", f"Request #{application.pk} was submitted for listing #{listing.pk}. Open Rental Requests to review it.")
    return application


@transaction.atomic
def decide_request(actor, request_id, action):
    # Scope before locking so an unrelated ID cannot disclose another participant's record.
    if action == "cancel":
        require_tenant(actor)
        records = RentalRequest.objects.filter(tenant=actor)
    else:
        require_verified_owner(actor)
        records = RentalRequest.objects.filter(listing__owner=actor)
    listing_id = records.values_list("listing_id", flat=True).get(pk=request_id)
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    application = records.select_for_update().get(pk=request_id)
    if action == "accept" and application.status == "accepted":
        # Retried clicks return the same draft; they never reserve a second room/version.
        from .models import RentalAgreement
        if RentalAgreement.objects.filter(rental_request=application).exists():
            return application
    if application.status != "pending":
        raise ValidationError("This request has already changed. Only pending requests can be updated.")
    if action not in ("cancel", "accept", "reject"):
        raise ValidationError("Choose a supported request action.")
    if action == "accept":
        require_verified_owner(actor, listing)
        require_tenant(application.tenant)
        validate_request_listing(listing, application.preferred_move_in, application.total_occupancy)
    application.status = {"cancel": "cancelled", "accept": "accepted", "reject": "rejected"}[action]
    application.responded_at = timezone.now()
    application.save(update_fields=["status", "responded_at"])
    if action == "accept":
        from .agreement_services import create_draft_locked
        create_draft_locked(actor, listing, application)
    recipient = listing.owner if action == "cancel" else application.tenant
    create_notification(recipient, f"Rental request {application.status}", f"Request #{application.pk} for listing #{listing.pk} has been {application.status}.")
    # Acceptance, reservation and draft creation commit together under the listing lock.
    return application
