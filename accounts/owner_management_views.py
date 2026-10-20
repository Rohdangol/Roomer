from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from listings.models import ListingRevision, RoomImage, RoomListing
from listings.services import (DRAFT_FIELDS, add_listing_photo, change_listing_availability,
    create_listing_draft, editable_listing_revision, require_owner, save_listing_draft, submit_listing_revision)
from .owner_listing_forms import OwnerListingForm, listing_form_sections
from .owner_revision_preview import pending_changes
from .permissions import owner_needs_verification


def owned_listing(user, pk):
    # Apply ownership in the lookup so other owners' IDs disclose no listing data.
    return get_object_or_404(RoomListing.objects.filter(owner=user, archived_at__isnull=True)
        .select_related("published_revision"), pk=pk)


@login_required(login_url="accounts:login")
@require_GET
def details(request, pk):
    require_owner(request.user)
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    listing = owned_listing(request.user, pk)
    latest = listing.revisions.order_by("-version").prefetch_related("photos", "amenity_links__amenity").first()
    pending = listing.revisions.filter(approval_status="pending").first()
    # Main details always use the publication snapshot; pending content is modal-only.
    # A never-approved listing has no approved version to substitute for its submission.
    revision = listing.published_revision or pending or latest
    changes = pending_changes(listing.published_revision, pending)
    point = None
    if revision:
        point = {"latitude": float(revision.latitude), "longitude": float(revision.longitude)}
    can_activate = (listing.listing_status == "inactive" and listing.published_revision_id
        and latest and latest.approval_status == "approved"
        and listing.published_revision.approval_status == "approved")
    return render(request, "accounts/owner_listing_details.html", {
        "listing": listing, "revision": revision, "photos": list(revision.photos.all()) if revision else [],
        "location_point": point, "can_edit": bool(latest),
        "pending_revision": pending, "preview_changes": changes, "latest_revision": latest,
        "showing_published": bool(revision and revision.pk == listing.published_revision_id),
        "can_activate": can_activate,
        "last_updated": max(listing.updated_at, revision.updated_at) if revision else listing.updated_at,
    })


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def edit(request, pk):
    require_owner(request.user)
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    listing = owned_listing(request.user, pk)
    source = editable_listing_revision(listing)
    if source is None:
        messages.warning(request, "No listing details are available to edit.")
        return redirect("accounts:owner_listing_details", pk=pk)
    # Bind to an unsaved instance: submitted revision objects must remain immutable.
    instance = ListingRevision(**{name: getattr(source, name) for name in DRAFT_FIELDS})
    form = OwnerListingForm(request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None, instance=instance, source=source)
    saved_photos = []
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                locked = RoomListing.objects.select_for_update().get(pk=listing.pk)
                require_owner(request.user, locked)
                current = editable_listing_revision(locked)
                # Reject stale edit tabs and submissions racing with admin review.
                if (locked.archived_at
                    or form.cleaned_data["source_version"] != f"{current.pk}:{current.updated_at.isoformat()}"):
                    raise ValidationError("This listing changed. Reload the edit page before submitting again.")
                draft = current if current.approval_status == "draft" else create_listing_draft(request.user, pk)
                save_listing_draft(request.user, draft.pk,
                    {name: form.cleaned_data[name] for name in DRAFT_FIELDS},
                    amenity_ids=[item.pk for item in form.cleaned_data["amenities"]])
                removed = {photo.pk for photo in form.cleaned_data["remove_photos"]}
                retained = [photo for photo in current.photos.all() if photo.pk not in removed]
                # Rebuild only draft associations; historical files are shared and never deleted.
                draft.photos.all().delete()
                for position, photo in enumerate(retained, 1):
                    RoomImage.objects.create(revision=draft, image=photo.image.name, position=position)
                for position, image in enumerate(form.cleaned_data["photos"], len(retained) + 1):
                    saved_photos.append(add_listing_photo(request.user, draft.pk, image, position))
                submit_listing_revision(request.user, draft.pk)
                locked.updated_at = timezone.now()
                locked.save(update_fields=["updated_at"])
        except Exception as error:
            for photo in saved_photos:
                photo.image.storage.delete(photo.image.name)
            if isinstance(error, ValidationError):
                if hasattr(error, "error_dict"):
                    for field, errors in error.error_dict.items():
                        form.add_error(field if field in form.fields else None, errors)
                else:
                    for message in error.messages:
                        form.add_error(None, message)
            elif isinstance(error, OSError):
                form.add_error(None, "Photos could not be saved. Please retry.")
            else:
                raise
        else:
            messages.success(request, "Changes submitted for Admin review. You can edit and resubmit; published details remain unchanged until approval.")
            url = reverse("accounts:owner_listing_details", args=[pk])
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"redirect_url": url})
            return redirect(url)
    return render(request, "accounts/owner_add_listing.html", {
        "form": form, "sections": listing_form_sections(form), "editing": True, "listing": listing,
        "existing_photos": list(source.photos.all()),
        "removed_photo_ids": request.POST.getlist("remove_photos") if request.method == "POST" else [],
    })


@login_required(login_url="accounts:login")
@require_POST
def availability(request, pk):
    require_owner(request.user)
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    listing = owned_listing(request.user, pk)
    try:
        with transaction.atomic():
            listing = RoomListing.objects.select_for_update().get(pk=listing.pk)
            require_owner(request.user, listing)
            action = request.POST.get("action")
            if request.POST.get("confirm") != "yes":
                raise ValidationError("Confirm the availability change before submitting.")
            if listing.archived_at:
                raise ValidationError("Archived listings cannot change availability here.")
            if action == "activate":
                latest = listing.revisions.order_by("-version").first()
                if listing.listing_status != "inactive" or latest is None or latest.approval_status != "approved":
                    raise ValidationError("Activation requires approved listing details with no pending or rejected changes.")
            elif action != "deactivate" or listing.listing_status != "available":
                raise ValidationError("Only available listings can be deactivated. Occupied listings cannot change availability.")
            change_listing_availability(request.user, listing.pk, action)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, "Listing activated." if action == "activate" else "Listing deactivated.")
    return redirect("accounts:owner_listing_details", pk=pk)
