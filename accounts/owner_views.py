from mimetypes import guess_type

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from listings.models import ListingRevision, RoomImage, RoomListing
from rentals.models import RentalAgreement, RentalRequest
from .models import User
from .permissions import owner_needs_verification


@login_required(login_url="accounts:login")
@require_GET
def home(request):
    if not request.user.is_active or request.user.is_staff or request.user.role != User.Role.OWNER:
        return HttpResponseForbidden("This page is available to active owners only.")
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    # Scope every dashboard query to this owner, including unpublished listings.
    listings = RoomListing.objects.filter(owner=request.user, archived_at__isnull=True).select_related(
        "published_revision").prefetch_related("published_revision__photos")
    recent_listings = listings.prefetch_related(Prefetch(
        "revisions", queryset=ListingRevision.objects.order_by("-version").prefetch_related("photos"),
        to_attr="dashboard_revisions",
    )).order_by("-updated_at", "-pk")[:3]
    return render(request, "accounts/owner_home.html", {
        "page_title": "Owner Dashboard",
        "active_listings": listings.filter(
            listing_status=RoomListing.Status.AVAILABLE, published_revision__isnull=False,
        ).count(),
        "recent_listings": recent_listings,
        "pending_requests": RentalRequest.objects.filter(listing__owner=request.user, status="pending").count(),
        "active_rentals": RentalAgreement.objects.filter(owner=request.user, status="active").count(),
        "recent_requests": RentalRequest.objects.filter(listing__owner=request.user).select_related("tenant", "listing_revision")[:3],
    })


@login_required(login_url="accounts:login")
@require_GET
def request_tenant_photo(request, pk):
    if (not request.user.is_active or request.user.is_staff
            or request.user.role != User.Role.OWNER or owner_needs_verification(request.user)):
        return HttpResponseForbidden("This photo is available to verified owners only.")
    # A request identifier grants access only to the tenant who applied to this owner's listing.
    application = RentalRequest.objects.filter(pk=pk, listing__owner=request.user).select_related("tenant").first()
    if application is None or not application.tenant.profile_picture:
        raise Http404
    picture = application.tenant.profile_picture
    try:
        stream = picture.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404
    response = FileResponse(stream, content_type=guess_type(picture.name)[0] or "application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required(login_url="accounts:login")
@require_GET
def listing_photo(request, pk):
    if not request.user.is_active or request.user.is_staff or request.user.role != User.Role.OWNER:
        return HttpResponseForbidden("This page is available to active owners only.")
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    # Private draft photos must never be served by file ID alone.
    photo = RoomImage.objects.filter(pk=pk, revision__listing__owner=request.user,
        revision__listing__archived_at__isnull=True).first()
    if photo is None:
        raise Http404
    try:
        image = photo.image.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404
    response = FileResponse(image, content_type=guess_type(photo.image.name)[0] or "application/octet-stream")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required(login_url="accounts:login")
@require_GET
def my_listings(request):
    if not request.user.is_active or request.user.is_staff or request.user.role != User.Role.OWNER:
        return HttpResponseForbidden("This page is available to active owners only.")
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    # Apply ownership before filtering or counting; archived photos are also unavailable.
    listings = RoomListing.objects.filter(owner=request.user, archived_at__isnull=True).select_related(
        "published_revision").prefetch_related("published_revision__photos")
    has_listings = listings.exists()
    status = request.GET.get("status", "all")
    if status not in RoomListing.Status.values:
        status = "all"
    if status != "all":
        listings = listings.filter(listing_status=status)
    listings = listings.prefetch_related(Prefetch(
        "revisions", queryset=ListingRevision.objects.order_by("-version").prefetch_related("photos"),
        to_attr="dashboard_revisions",
    )).order_by("-updated_at", "-pk")
    page = Paginator(listings, 6).get_page(request.GET.get("page"))
    return render(request, "accounts/owner_listings.html", {
        "page_title": "My Listings", "page_obj": page, "status": status,
        "status_filters": [("all", "All"), *RoomListing.Status.choices],
        "has_listings": has_listings,
        "page_numbers": page.paginator.get_elided_page_range(page.number),
    })


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def add_listing(request):
    from listings.services import (DRAFT_FIELDS, add_listing_photo, create_listing,
        save_listing_draft, submit_listing_revision)
    from .owner_listing_forms import OwnerListingForm, listing_form_sections

    if not request.user.is_active or request.user.is_staff or request.user.role != User.Role.OWNER:
        return HttpResponseForbidden("This page is available to active owners only.")
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    form = OwnerListingForm(request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        saved_photos = []
        try:
            # Roll back every record together; storage files need explicit cleanup below.
            with transaction.atomic():
                revision = create_listing(request.user,
                    **{name: form.cleaned_data[name] for name in DRAFT_FIELDS})
                save_listing_draft(request.user, revision.pk, {},
                    amenity_ids=[amenity.pk for amenity in form.cleaned_data["amenities"]])
                for position, image in enumerate(form.cleaned_data["photos"], 1):
                    saved_photos.append(add_listing_photo(request.user, revision.pk, image, position))
                submit_listing_revision(request.user, revision.pk)
        except Exception as error:
            # These files belong only to the rolled-back creation, never historical photos.
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
                form.add_error(None, "Photos could not be saved. Please select them again and retry.")
            else:
                raise
        else:
            messages.success(request, "Listing submitted successfully. It will become available after admin approval.")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"redirect_url": reverse("accounts:owner_listings")})
            return redirect("accounts:owner_listings")
    return render(request, "accounts/owner_add_listing.html", {"form": form,
        "sections": listing_form_sections(form)})
