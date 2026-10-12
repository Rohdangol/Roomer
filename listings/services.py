from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.permissions import owner_needs_verification
from notifications.services import create_notification
from .models import Amenity, ListingAmenity, ListingRevision, RoomImage, RoomListing
from .storage import validate_photo


DRAFT_FIELDS = (
    "title", "description", "city", "locality", "address", "latitude", "longitude",
    "room_type", "furnishing", "monthly_rent", "security_deposit", "available_from",
    "maximum_occupants", "floor", "bathroom_details", "cooking_allowed", "visitors_allowed",
    "smoking_allowed", "pets_allowed", "quiet_hours_start", "quiet_hours_end", "additional_rules",
)


def published_listings():
    return RoomListing.objects.filter(
        listing_status="available", archived_at__isnull=True, owner__is_active=True,
        published_revision__approval_status="approved",
    ).select_related("owner", "published_revision")


def require_owner(actor, listing=None):
    if not actor.is_authenticated or not actor.is_active or actor.is_staff or actor.role != "owner":
        raise PermissionDenied("An active owner account is required.")
    if listing and listing.owner_id != actor.pk:
        raise PermissionDenied("This listing belongs to another owner.")


def require_manager(actor, listing):
    if actor.is_authenticated and actor.is_active and actor.is_staff and actor.has_perm("listings.change_roomlisting"):
        return
    require_owner(actor, listing)


def locked_draft(actor, revision_id):
    # Always lock listing before revision; submission/review use the same order.
    listing_id = ListingRevision.objects.values_list("listing_id", flat=True).get(pk=revision_id)
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    require_owner(actor, listing)
    revision = ListingRevision.objects.select_for_update().get(pk=revision_id)
    if revision.approval_status != "draft":
        raise ValidationError("Only drafts can be edited.")
    return listing, revision


@transaction.atomic
def create_listing(actor, **details):
    require_owner(actor)
    listing = RoomListing(owner=actor)
    listing.full_clean()
    listing.save()
    revision = ListingRevision(listing=listing, version=1)
    apply_details(revision, details)
    revision.full_clean()
    revision.save()
    return revision


def apply_details(revision, details):
    if set(details) - set(DRAFT_FIELDS):
        raise ValidationError("Only editable listing details may be supplied.")
    for name, value in details.items():
        setattr(revision, name, value)


@transaction.atomic
def create_listing_draft(actor, listing_id):
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    require_owner(actor, listing)
    if listing.revisions.filter(approval_status="draft").exists():
        raise ValidationError("This listing already has a draft.")
    source = listing.published_revision or listing.revisions.order_by("-version").first()
    if source is None:
        raise ValidationError("Create initial content with create_listing().")
    version = listing.revisions.aggregate(last=Max("version"))["last"] + 1
    draft = ListingRevision(listing=listing, version=version, **{name: getattr(source, name) for name in DRAFT_FIELDS})
    draft.full_clean()
    draft.save()
    # Copy associations/file references; never overwrite or remove approved files.
    ListingAmenity.objects.bulk_create([ListingAmenity(revision=draft, amenity_id=value) for value in source.amenity_links.values_list("amenity_id", flat=True)])
    RoomImage.objects.bulk_create([RoomImage(revision=draft, image=photo.image.name, position=photo.position) for photo in source.photos.all()])
    return draft


@transaction.atomic
def save_listing_draft(actor, revision_id, details, amenity_ids=None):
    listing, revision = locked_draft(actor, revision_id)
    apply_details(revision, details)
    revision.full_clean()
    revision.save()
    if amenity_ids is not None:
        ids = set(amenity_ids)
        if Amenity.objects.filter(pk__in=ids).count() != len(ids):
            raise ValidationError("Choose existing amenities.")
        revision.amenity_links.all().delete()
        ListingAmenity.objects.bulk_create([ListingAmenity(revision=revision, amenity_id=value) for value in ids])
    return revision


@transaction.atomic
def add_listing_photo(actor, revision_id, image, position):
    listing, revision = locked_draft(actor, revision_id)
    photo = RoomImage(revision=revision, image=image, position=position)
    photo.full_clean()
    try:
        photo.save()
    except Exception:
        # Only clean up this newly written file, never shared historical references.
        if photo.image and photo.image._committed:
            photo.image.storage.delete(photo.image.name)
        raise
    return photo


@transaction.atomic
def remove_listing_photo(actor, photo_id):
    photo = RoomImage.objects.get(pk=photo_id)
    locked_draft(actor, photo.revision_id)
    photo.delete()  # File is retained: a published snapshot may reference the same path.


@transaction.atomic
def reorder_listing_photos(actor, revision_id, photo_ids):
    listing, revision = locked_draft(actor, revision_id)
    photos = {photo.pk: photo for photo in revision.photos.all()}
    if len(photo_ids) != len(set(photo_ids)) or set(photo_ids) != set(photos):
        raise ValidationError("Supply every draft photo exactly once.")
    # Rebuild draft associations to avoid transient unique-position conflicts.
    revision.photos.all().delete()
    RoomImage.objects.bulk_create([RoomImage(revision=revision, image=photos[pk].image.name, position=index) for index, pk in enumerate(photo_ids, 1)])


def validate_publication(revision):
    revision.full_clean()
    photos = list(revision.photos.all())
    if not 1 <= len(photos) <= 10:
        raise ValidationError("Submission requires 1–10 photos.")
    for photo in photos:
        with photo.image.open("rb") as content:
            validate_photo(content)


@transaction.atomic
def submit_listing_revision(actor, revision_id):
    listing, revision = locked_draft(actor, revision_id)
    if owner_needs_verification(actor):
        raise PermissionDenied("Owner verification approval is required.")
    if listing.revisions.filter(approval_status="pending").exists():
        raise ValidationError("This listing already has a pending revision.")
    validate_publication(revision)
    # Narrow updates are reserved for locked transitions, bypassing immutable save().
    now = timezone.now()
    ListingRevision.objects.filter(pk=revision.pk).update(approval_status="pending", submitted_at=now, updated_at=now)
    revision.refresh_from_db()
    return revision


@transaction.atomic
def review_listing_revision(actor, revision_id, decision, rejection_reason=""):
    if not actor.is_authenticated or not actor.is_active or not actor.is_staff or not actor.has_perm("listings.change_listingrevision"):
        raise PermissionDenied("Listing review permission is required.")
    listing_id = ListingRevision.objects.values_list("listing_id", flat=True).get(pk=revision_id)
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    revision = ListingRevision.objects.select_for_update().get(pk=revision_id)
    if listing.owner_id == actor.pk:
        raise PermissionDenied("Owners cannot approve their own listings.")
    if revision.approval_status != "pending":
        raise ValidationError("This submitted version has already been reviewed or is not pending.")
    reason = rejection_reason.strip()
    if decision not in ("approved", "rejected") or (decision == "rejected" and not reason):
        raise ValidationError("Choose approval or rejection; rejection requires a reason.")
    if decision == "approved":
        validate_publication(revision)
    now = timezone.now()
    ListingRevision.objects.filter(pk=revision.pk).update(approval_status=decision, reviewed_by=actor, reviewed_at=now, rejection_reason=reason if decision == "rejected" else "", updated_at=now)
    if decision == "approved":
        if listing.published_revision_id is None:
            listing.listing_status = "available"
            listing.published_at = now
        revision.refresh_from_db()
        listing.published_revision = revision
        listing.full_clean()
        listing.save()
    create_notification(listing.owner, "Listing review completed", f"Listing #{listing.pk} revision {revision.version} was {decision}." + (f" {reason}" if decision == "rejected" else ""))
    revision.refresh_from_db()
    return revision


@transaction.atomic
def change_listing_availability(actor, listing_id, action):
    listing = RoomListing.objects.select_for_update().get(pk=listing_id)
    require_manager(actor, listing)
    if action not in ("activate", "deactivate", "archive", "restore"):
        raise ValidationError("Choose a supported listing action.")
    # Phase one has no agreements: block every occupied record, never fake a lookup.
    if listing.listing_status == "occupied":
        raise ValidationError("Occupied listings cannot change availability or be archived.")
    is_admin = actor.is_staff
    if action == "activate":
        if listing.archived_at or not listing.published_revision_id or listing.published_revision.approval_status != "approved" or not listing.owner.is_active or owner_needs_verification(listing.owner):
            raise ValidationError("Only an eligible approved, unarchived listing can be activated.")
        listing.listing_status = "available"
    elif action == "deactivate":
        listing.listing_status = "inactive"
    elif action == "archive":
        if listing.archive_source == "admin" and not is_admin:
            raise PermissionDenied("Only an admin can change an admin archive.")
        listing.archived_at = timezone.now()
        listing.archived_by = actor
        listing.archive_source = "admin" if is_admin else "owner"
    else:
        if not listing.archived_at:
            raise ValidationError("This listing is not archived.")
        if listing.archive_source == "admin" and not is_admin:
            raise PermissionDenied("Only an admin can restore an admin archive.")
        listing.archived_at = None
        listing.archived_by = None
        listing.archive_source = ""
        listing.listing_status = "inactive"
    listing.full_clean()
    listing.save()
    return listing
