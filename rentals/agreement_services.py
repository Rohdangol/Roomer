from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.permissions import owner_needs_verification
from listings.models import RoomListing
from notifications.services import create_notification
from .models import AgreementTerms, RentalAgreement, RentalRequest
from .services import require_tenant, require_verified_owner, validate_request_listing


def local_today():
    return timezone.localdate(timezone=ZoneInfo("Asia/Kathmandu"))


def notify_parties(agreement, event):
    for recipient in (agreement.tenant, agreement.owner):
        create_notification(recipient, f"Agreement {event}", f"Agreement #{agreement.pk}, version {agreement.current_terms.version}, has been {event}.")


def scoped_agreements(actor):
    if not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("An active account is required.")
    if actor.is_staff:
        if not actor.has_perm("rentals.view_rentalagreement"):
            raise PermissionDenied("Agreement view permission is required.")
        return RentalAgreement.objects.all()
    if actor.role == "owner":
        require_verified_owner(actor)
        return RentalAgreement.objects.filter(owner=actor)
    require_tenant(actor)
    # An Owner's unsent preparation is private until that agreement has been sent.
    return RentalAgreement.objects.filter(tenant=actor, pk__in=AgreementTerms.objects.filter(sent_at__isnull=False).values("agreement_id"))


def locked_agreement(actor, agreement_id):
    records = scoped_agreements(actor)
    listing_id = records.values_list("listing_id", flat=True).get(pk=agreement_id)
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    agreement = records.select_for_update(of=("self",)).select_related("current_terms", "tenant", "owner").get(pk=agreement_id)
    return listing, agreement


def party_snapshot(user):
    # Contact terms are retained for the participants; identity document paths are never copied.
    return {"full_name": user.full_name, "email": user.email, "phone_number": user.phone_number}


@transaction.atomic
def prepare_agreement(actor, request_id, details, expected_terms_id=None):
    require_verified_owner(actor)
    records = RentalRequest.objects.filter(listing__owner=actor)
    listing_id = records.values_list("listing_id", flat=True).get(pk=request_id)
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    application = records.select_for_update().get(pk=request_id)
    if application.status != "accepted":
        raise ValidationError("Only accepted rental requests can proceed to an agreement.")
    require_tenant(application.tenant)
    if set(details) != {"monthly_rent", "security_deposit", "payment_due_day", "start_date", "end_date", "additional_terms"}:
        raise ValidationError("Supply the agreement terms only.")
    start = details["start_date"]
    if start < local_today():
        raise ValidationError("Agreement start must be today or later.")
    validate_request_listing(listing, start, application.total_occupancy)
    agreement = RentalAgreement.objects.filter(rental_request=application).first()
    if agreement:
        if agreement.status != "pending" or agreement.current_terms_id != expected_terms_id:
            raise ValidationError("This agreement has changed. Reload before preparing new terms.")
    else:
        if expected_terms_id is not None:
            raise ValidationError("This agreement has changed. Reload before preparing new terms.")
        agreement = RentalAgreement(rental_request=application, listing=listing, tenant=application.tenant, owner=actor)
        agreement.full_clean()
        agreement.save()
    previous = agreement.versions.aggregate(last=Max("version"))["last"] or 0
    revision = listing.published_revision
    snapshot_fields = ("title", "city", "locality", "address", "room_type", "furnishing", "maximum_occupants",
        "cooking_allowed", "visitors_allowed", "smoking_allowed", "pets_allowed", "additional_rules")
    snapshot = {name: getattr(revision, name) for name in snapshot_fields}
    snapshot.update(room_type_label=revision.get_room_type_display(), furnishing_label=revision.get_furnishing_display())
    snapshot.update(quiet_hours_start=str(revision.quiet_hours_start or ""), quiet_hours_end=str(revision.quiet_hours_end or ""))
    terms = AgreementTerms(agreement=agreement, version=previous + 1, listing_revision=revision,
        total_occupancy=application.total_occupancy, listing_snapshot=snapshot,
        tenant_snapshot=party_snapshot(application.tenant), owner_snapshot=party_snapshot(actor), **details)
    terms.full_clean()
    terms.save()
    agreement.current_terms = terms
    agreement.save(update_fields=["current_terms"])
    # Editing creates a new unconfirmed version; old sent/confirmed versions remain intact.
    return agreement


def require_current_terms(agreement, terms_id):
    if agreement.current_terms_id != terms_id:
        raise ValidationError("The agreement terms have changed. Reload and review the current version.")
    if agreement.status != "pending":
        raise ValidationError("Only pending agreements can be sent, confirmed or finalized.")
    return agreement.current_terms


@transaction.atomic
def send_agreement(actor, agreement_id, terms_id):
    require_verified_owner(actor)
    listing, agreement = locked_agreement(actor, agreement_id)
    terms = require_current_terms(agreement, terms_id)
    if terms.sent_at:
        raise ValidationError("This version has already been sent.")
    if terms.start_date < local_today():
        raise ValidationError("Prepare updated dates before sending this agreement.")
    validate_request_listing(listing, terms.start_date, terms.total_occupancy)
    AgreementTerms.objects.filter(pk=terms.pk).update(sent_at=timezone.now())
    create_notification(agreement.tenant, "Agreement ready for confirmation", f"Review agreement #{agreement.pk}, version {terms.version}, in My Agreements.")
    return agreement


@transaction.atomic
def confirm_agreement(actor, agreement_id, terms_id):
    require_tenant(actor)
    listing, agreement = locked_agreement(actor, agreement_id)
    terms = require_current_terms(agreement, terms_id)
    if not terms.sent_at or terms.tenant_accepted_at:
        raise ValidationError("This version has not been sent or has already been confirmed.")
    if terms.start_date < local_today():
        raise ValidationError("Ask the Owner to update the dates and send a new version.")
    validate_request_listing(listing, terms.start_date, terms.total_occupancy)
    AgreementTerms.objects.filter(pk=terms.pk).update(tenant_accepted_at=timezone.now())
    create_notification(agreement.owner, "Agreement confirmed by Tenant", f"The Tenant confirmed agreement #{agreement.pk}, version {terms.version}. Review and finalize it.")
    return agreement


def activate_locked(listing, agreement):
    # Called under the same listing lock for immediate and scheduled activation.
    agreement.status = "active"
    agreement.activated_at = timezone.now()
    agreement.save(update_fields=["status", "activated_at"])
    listing.listing_status = "occupied"
    listing.save(update_fields=["listing_status", "updated_at"])
    notify_parties(agreement, "activated")


@transaction.atomic
def finalize_agreement(actor, agreement_id, terms_id):
    require_verified_owner(actor)
    listing, agreement = locked_agreement(actor, agreement_id)
    terms = require_current_terms(agreement, terms_id)
    require_tenant(agreement.tenant)
    if not terms.sent_at or not terms.tenant_accepted_at or terms.owner_accepted_at:
        raise ValidationError("Tenant confirmation of this exact version is required before finalization.")
    if terms.start_date < local_today():
        raise ValidationError("The start date is in the past. Prepare updated terms, send them and obtain fresh Tenant confirmation.")
    validate_request_listing(listing, terms.start_date, terms.total_occupancy)
    if RentalAgreement.objects.filter(listing=listing, status__in=["scheduled", "active"]).exclude(pk=agreement.pk).exists():
        raise ValidationError("This listing already has a Scheduled or Active agreement.")
    AgreementTerms.objects.filter(pk=terms.pk).update(owner_accepted_at=timezone.now())
    notify_parties(agreement, "finalized")
    if terms.start_date == local_today():
        activate_locked(listing, agreement)
    else:
        agreement.status = "scheduled"
        agreement.save(update_fields=["status"])
        listing.listing_status = "reserved"
        listing.save(update_fields=["listing_status", "updated_at"])
    return agreement


@transaction.atomic
def activate_scheduled(agreement_id):
    listing_id = RentalAgreement.objects.values_list("listing_id", flat=True).get(pk=agreement_id)
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    agreement = RentalAgreement.objects.select_for_update(of=("self",)).select_related("current_terms", "tenant", "owner").get(pk=agreement_id)
    if agreement.status != "scheduled" or agreement.current_terms.start_date > local_today():
        return False
    # A binding reservation survives suspension/archive; it does not make the listing public.
    activate_locked(listing, agreement)
    return True


@transaction.atomic
def complete_agreement(actor, agreement_id, terms_id):
    listing, agreement = locked_agreement(actor, agreement_id)
    if actor.is_staff:
        if not actor.has_perm("rentals.change_rentalagreement"):
            raise PermissionDenied("Agreement change permission is required.")
    else:
        require_verified_owner(actor, listing)
    if agreement.current_terms_id != terms_id or agreement.status != "active":
        raise ValidationError("Only an Active agreement with unchanged terms can be completed.")
    if local_today() < agreement.current_terms.end_date:
        raise ValidationError("Completion is permitted only on or after the agreement end date.")
    agreement.status = "completed"
    agreement.completed_at = timezone.now()
    agreement.completed_by = actor
    agreement.save(update_fields=["status", "completed_at", "completed_by"])
    eligible = (not listing.archived_at and listing.archive_source != "admin" and listing.published_revision_id
        and listing.published_revision.approval_status == "approved" and listing.owner.is_active
        and listing.owner.role == "owner" and not listing.owner.is_staff and not owner_needs_verification(listing.owner))
    listing.listing_status = "available" if eligible else "inactive"
    listing.save(update_fields=["listing_status", "updated_at"])
    notify_parties(agreement, "completed")
    return agreement
