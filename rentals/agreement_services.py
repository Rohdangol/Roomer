from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.permissions import owner_needs_verification
from listings.models import RoomListing
from notifications.services import create_notification
from .models import AgreementReview, AgreementTerms, RentalAgreement, RentalRequest
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


def snapshot_terms(agreement, revision, details):
    fields = ("title", "city", "locality", "address", "room_type", "furnishing", "maximum_occupants",
        "cooking_allowed", "visitors_allowed", "smoking_allowed", "pets_allowed", "additional_rules")
    snapshot = {name: getattr(revision, name) for name in fields}
    snapshot.update(room_type_label=revision.get_room_type_display(), furnishing_label=revision.get_furnishing_display(),
        quiet_hours_start=str(revision.quiet_hours_start or ""), quiet_hours_end=str(revision.quiet_hours_end or ""))
    version = (agreement.versions.aggregate(last=Max("version"))["last"] or 0) + 1
    terms = AgreementTerms(agreement=agreement, version=version, listing_revision=revision,
        total_occupancy=agreement.rental_request.total_occupancy, listing_snapshot=snapshot,
        tenant_snapshot=party_snapshot(agreement.tenant), owner_snapshot=party_snapshot(agreement.owner), **details)
    terms.full_clean()
    terms.save()
    agreement.current_terms = terms
    agreement.save(update_fields=["current_terms"])
    return terms


def create_draft_locked(actor, listing, application):
    """Caller holds listing/request locks inside an atomic acceptance/preparation."""
    existing = RentalAgreement.objects.filter(rental_request=application).first()
    if existing:
        return existing
    if RentalAgreement.objects.filter(listing=listing).exclude(status__in=["completed", "pending"]).exists():
        raise ValidationError("This room already has a reservation or rental agreement.")
    if RentalRequest.objects.filter(listing=listing, status="accepted").exclude(pk=application.pk).exists():
        raise ValidationError("Another accepted request exists. Resolve the legacy conflict before reserving this room.")
    validate_request_listing(listing, application.preferred_move_in, application.total_occupancy)
    agreement = RentalAgreement(rental_request=application, listing=listing, tenant=application.tenant,
        owner=actor, status="draft", workflow_version=2, release_status=listing.listing_status)
    agreement.full_clean()
    agreement.save()
    revision = application.listing_revision
    snapshot_terms(agreement, revision, {"monthly_rent": revision.monthly_rent,
        "security_deposit": revision.security_deposit, "payment_due_day": None,
        "start_date": application.preferred_move_in, "end_date": None, "additional_terms": ""})
    listing.listing_status = "reserved"
    listing.save(update_fields=["listing_status", "updated_at"])
    return agreement


@transaction.atomic
def prepare_agreement(actor, request_id, details, expected_terms_id=None):
    require_verified_owner(actor)
    records = RentalRequest.objects.filter(listing__owner=actor)
    listing_id = records.values_list("listing_id", flat=True).get(pk=request_id)
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    application = records.select_for_update().get(pk=request_id)
    if application.status != "accepted":
        raise ValidationError("Only accepted rental requests can proceed to an agreement.")
    agreement = RentalAgreement.objects.filter(rental_request=application).select_related("current_terms").first()
    if agreement is None:
        if expected_terms_id is not None:
            raise ValidationError("Reload before editing this agreement.")
        agreement = create_draft_locked(actor, listing, application)
    elif agreement.current_terms_id != expected_terms_id:
        raise ValidationError("This agreement has changed. Reload the current version.")
    if agreement.workflow_version != 2:
        raise ValidationError("Legacy agreements require an explicit migration decision before revision.")
    if agreement.status not in ("draft", "changes_requested"):
        raise ValidationError("Sent versions are read-only until returned for revision.")
    names = {"monthly_rent", "security_deposit", "payment_due_day", "start_date", "end_date", "additional_terms"}
    if set(details) != names:
        raise ValidationError("Supply only the permitted agreement terms.")
    if details["start_date"] < local_today():
        raise ValidationError("Agreement start must be today or later.")
    revision = agreement.current_terms.listing_revision
    # Changes create a new immutable version with no carried-forward consent or approval.
    snapshot_terms(agreement, revision, details)
    agreement.status = "draft"
    agreement.save(update_fields=["status"])
    return agreement


def require_current_terms(agreement, terms_id, states):
    if agreement.workflow_version != 2:
        raise ValidationError("Legacy agreement: no new consent or approval is inferred. Coordinate explicit migration first.")
    if agreement.current_terms_id != terms_id:
        raise ValidationError("The agreement terms have changed. Reload and review the current version.")
    if agreement.status not in states:
        raise ValidationError("This action is not available in the current agreement state.")
    return agreement.current_terms


def require_reservation(listing, agreement):
    if listing.listing_status != "reserved":
        raise ValidationError("The room reservation has changed. Contact an administrator.")
    if RentalAgreement.objects.filter(listing=listing).exclude(pk=agreement.pk).exclude(status__in=["completed", "pending"]).exists():
        raise ValidationError("Another agreement conflicts with this reservation.")


def validate_sendable(terms):
    if not terms.end_date or terms.end_date <= terms.start_date or not terms.payment_due_day or not terms.additional_terms.strip():
        raise ValidationError("Supply an end date after the start, payment due day and required terms before sending.")
    if terms.monthly_rent <= 0 or terms.security_deposit < 0:
        raise ValidationError("Rent must be positive and deposit nonnegative.")
    if terms.start_date < local_today():
        raise ValidationError("Revise the dates and obtain fresh consent; past start dates cannot be approved.")


@transaction.atomic
def send_agreement(actor, agreement_id, terms_id):
    require_verified_owner(actor)
    listing, agreement = locked_agreement(actor, agreement_id)
    terms = require_current_terms(agreement, terms_id, ["draft"])
    require_tenant(agreement.tenant)
    require_reservation(listing, agreement)
    validate_sendable(terms)
    if terms.sent_at:
        raise ValidationError("This version has already been sent.")
    now = timezone.now()
    AgreementTerms.objects.filter(pk=terms.pk).update(sent_at=now, owner_accepted_at=now)
    agreement.status = "awaiting_tenant"
    agreement.save(update_fields=["status"])
    create_notification(agreement.tenant, "Agreement ready for confirmation", f"Review agreement #{agreement.pk}, version {terms.version}, in My Agreements.")
    return agreement


@transaction.atomic
def confirm_agreement(actor, agreement_id, terms_id):
    require_tenant(actor)
    listing, agreement = locked_agreement(actor, agreement_id)
    terms = require_current_terms(agreement, terms_id, ["awaiting_tenant"])
    require_reservation(listing, agreement)
    if not terms.sent_at or not terms.owner_accepted_at or terms.tenant_accepted_at:
        raise ValidationError("Owner consent to this sent version is required.")
    validate_sendable(terms)
    AgreementTerms.objects.filter(pk=terms.pk).update(tenant_accepted_at=timezone.now())
    agreement.status = "pending_admin"
    agreement.save(update_fields=["status"])
    create_notification(agreement.owner, "Agreement confirmed by Tenant", f"Agreement #{agreement.pk}, version {terms.version}, awaits Admin approval.")
    from django.contrib.auth import get_user_model
    for reviewer in get_user_model().objects.filter(is_active=True, is_staff=True):
        if reviewer.has_perm("rentals.approve_rentalagreement") and reviewer.has_perm("rentals.view_rentalagreement"):
            create_notification(reviewer, "Agreement awaiting approval", f"Review agreement #{agreement.pk}, version {terms.version}.")
    return agreement


@transaction.atomic
def request_agreement_changes(actor, agreement_id, terms_id, reason):
    require_tenant(actor)
    listing, agreement = locked_agreement(actor, agreement_id)
    terms = require_current_terms(agreement, terms_id, ["awaiting_tenant"])
    require_reservation(listing, agreement)
    reason = reason.strip()
    if not reason:
        raise ValidationError("Explain the changes you are requesting.")
    AgreementReview.objects.create(terms=terms, reviewer=actor, decision="tenant_changes", reason=reason)
    agreement.status = "changes_requested"
    agreement.save(update_fields=["status"])
    create_notification(agreement.owner, "Agreement changes requested", f"Review the Tenant's explanation for agreement #{agreement.pk}, version {terms.version}.")
    return agreement


def require_agreement_reviewer(actor):
    if not actor.is_authenticated or not actor.is_active or not actor.is_staff or not all(actor.has_perm(p) for p in (
        "rentals.view_rentalagreement", "rentals.change_rentalagreement", "rentals.approve_rentalagreement")):
        raise PermissionDenied("Agreement view, change and approval permissions are required.")


@transaction.atomic
def review_agreement(actor, agreement_id, terms_id, decision, reason=""):
    require_agreement_reviewer(actor)
    listing, agreement = locked_agreement(actor, agreement_id)
    terms = require_current_terms(agreement, terms_id, ["pending_admin"])
    require_reservation(listing, agreement)
    if not terms.sent_at or not terms.owner_accepted_at or not terms.tenant_accepted_at:
        raise ValidationError("Both parties must consent to this exact version before Admin review.")
    if decision == "return":
        reason = reason.strip()
        if not reason:
            raise ValidationError("A reason is required when returning an agreement.")
        AgreementReview.objects.create(terms=terms, reviewer=actor, decision="admin_return", reason=reason)
        agreement.status = "changes_requested"
        agreement.save(update_fields=["status"])
        notify_parties(agreement, "returned for revision")
    elif decision == "approve":
        validate_sendable(terms)
        require_tenant(agreement.tenant)
        require_verified_owner(agreement.owner, listing)
        now = timezone.now()
        AgreementTerms.objects.filter(pk=terms.pk).update(approved_at=now, approved_by=actor)
        AgreementReview.objects.create(terms=terms, reviewer=actor, decision="admin_approve")
        # Refresh the in-memory proof before calling the same scheduler transition code.
        terms.approved_at, terms.approved_by = now, actor
        agreement.status = "scheduled"
        agreement.save(update_fields=["status"])
        notify_parties(agreement, "approved")
        if terms.start_date == local_today():
            activate_locked(listing, agreement)
    else:
        raise ValidationError("Choose approve or return for revision.")
    return agreement


def has_approval(agreement):
    terms = agreement.current_terms
    return bool(agreement.workflow_version == 2 and terms and terms.approved_at and terms.approved_by_id
        and terms.owner_accepted_at and terms.tenant_accepted_at and terms.sent_at)


def activate_locked(listing, agreement):
    terms = agreement.current_terms
    if not has_approval(agreement) or not terms.start_date <= local_today() <= terms.end_date:
        raise ValidationError("Activation requires current version approval, both consents and dates covering today.")
    agreement.status = "active"
    agreement.activated_at = timezone.now()
    agreement.save(update_fields=["status", "activated_at"])
    listing.listing_status = "occupied"
    listing.save(update_fields=["listing_status", "updated_at"])
    notify_parties(agreement, "activated")


def finish_locked(listing, agreement, actor=None):
    agreement.status = "completed"
    agreement.completed_at = timezone.now()
    agreement.completed_by = actor
    agreement.save(update_fields=["status", "completed_at", "completed_by"])
    eligible = (not listing.archived_at and listing.archive_source != "admin" and listing.published_revision_id
        and listing.published_revision.approval_status == "approved" and listing.owner.is_active
        and listing.owner.role == "owner" and not listing.owner.is_staff and not owner_needs_verification(listing.owner))
    # Never lift an inactive/admin-imposed state as a side effect of rental completion.
    if listing.listing_status in ("occupied", "reserved"):
        listing.listing_status = "available" if eligible and agreement.release_status == "available" else "inactive"
        listing.save(update_fields=["listing_status", "updated_at"])
    notify_parties(agreement, "completed")


@transaction.atomic
def activate_scheduled(agreement_id):
    listing_id = RentalAgreement.objects.values_list("listing_id", flat=True).get(pk=agreement_id)
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    agreement = RentalAgreement.objects.select_for_update(of=("self",)).select_related("current_terms", "tenant", "owner").get(pk=agreement_id)
    if not has_approval(agreement) or agreement.status not in ("scheduled", "active"):
        return False
    today = local_today()
    if today > agreement.current_terms.end_date:
        # Catch-up after downtime completes directly; no historical activation is fabricated.
        finish_locked(listing, agreement)
        return "completed"
    if agreement.status == "scheduled" and agreement.current_terms.start_date <= today:
        activate_locked(listing, agreement)
        return "activated"
    return False


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
    if agreement.workflow_version == 1:
        if local_today() < agreement.current_terms.end_date:
            raise ValidationError("Legacy completion is permitted only on or after its exclusive end date.")
        # Preserve the old release policy for legacy agreements without inventing consent.
        agreement.release_status = "available"
    elif not has_approval(agreement) or local_today() <= agreement.current_terms.end_date:
        raise ValidationError("Completion is permitted only after the inclusive end date.")
    finish_locked(listing, agreement, actor)
    return agreement


def finalize_agreement(actor, agreement_id, terms_id):
    raise ValidationError("Owner finalization has been replaced by consent on send and Admin approval.")
