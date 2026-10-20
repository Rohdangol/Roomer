from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import OuterRef, Prefetch, Q, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from listings.models import ListingRevision, RoomImage, RoomListing
from .admin_dashboard_views import can_view, require_staff
from .admin_listing_forms import AdminListingFilterForm, ListingDecisionForm


def require_listing_view(request):
    require_staff(request.user)
    # Listing and revision contents retain their existing separate permission checks.
    if not can_view(request, RoomListing) or not can_view(request, ListingRevision):
        raise PermissionDenied("Listing and revision view permissions are required.")


@login_required(login_url="accounts:login")
@require_GET
def listings(request):
    require_listing_view(request)
    parameters = request.GET.copy()
    parameters.setdefault("status", "all")
    form = AdminListingFilterForm(parameters)
    records = RoomListing.objects.all()
    has_listings = records.exists()
    owner = None
    if form.is_valid():
        owner = form.cleaned_data["owner"]
        if owner:
            records = records.filter(owner=owner)
            has_listings = records.exists()
        status = form.cleaned_data["status"] or "all"
        if status != "all":
            records = records.filter(listing_status=status)
        query = form.cleaned_data["q"]
        if query:
            # Search the displayed latest revision, not a different historical title/location.
            latest = ListingRevision.objects.filter(listing_id=OuterRef("pk")).order_by("-version")
            records = records.annotate(**{
                "latest_" + field: Subquery(latest.values(field)[:1])
                for field in ("title", "city", "locality", "address")
            }).filter(Q(latest_title__icontains=query) | Q(latest_city__icontains=query)
                | Q(latest_locality__icontains=query) | Q(latest_address__icontains=query)
                | Q(owner__full_name__icontains=query) | Q(owner__email__icontains=query))
    else:
        # Invalid filters must not return an unfiltered directory.
        records = records.none()
    records = records.select_related("owner").prefetch_related(Prefetch("revisions",
        queryset=ListingRevision.objects.order_by("-version").prefetch_related("photos"),
        to_attr="dashboard_revisions")).order_by("-created_at", "-pk")
    page = Paginator(records, 6).get_page(request.GET.get("page"))
    parameters.pop("page", None)
    return render(request, "custom_admin/listings.html", {
        "form": form, "page_obj": page, "page_numbers": page.paginator.get_elided_page_range(page.number),
        "pagination_query": parameters.urlencode(), "has_listings": has_listings,
        "owner_filter": parameters.get("owner", ""), "filtered_owner": owner,
        "status": parameters.get("status", "all"), "query": parameters.get("q", ""),
        "status_filters": [("all", "All"), *RoomListing.Status.choices],
        "can_photos": can_view(request, RoomImage),
    })


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def details(request, pk):
    from .models import OwnerVerification, User
    from .verification_services import email_is_verified

    require_listing_view(request)
    listing = get_object_or_404(RoomListing.objects.select_related("owner", "published_revision"), pk=pk)
    pending_revision = listing.revisions.filter(approval_status="pending").first()
    revision = pending_revision or listing.revisions.order_by("-version").first()
    selected_id = request.GET.get("revision")
    if selected_id:
        if not selected_id.isdecimal() or len(selected_id) > 18:
            raise Http404
        revision = get_object_or_404(listing.revisions, pk=selected_id)
    can_review = request.user.has_perm("listings.change_listingrevision") and listing.owner_id != request.user.pk
    if request.method == "POST" and not can_review:
        raise PermissionDenied("Listing approval permission is required; self review is not allowed.")
    form = ListingDecisionForm(request.POST if request.method == "POST" else None, initial={
        "revision_id": revision.pk if revision else None,
        "submitted_version": revision.submitted_at.isoformat() if revision and revision.submitted_at else "",
    })
    if request.method == "POST" and form.is_valid():
        from listings.services import review_listing_revision
        try:
            with transaction.atomic():
                # Preserve the service's listing-before-revision lock order and bind the
                # decision to exactly the version whose submitted content was reviewed.
                RoomListing.objects.select_for_update().get(pk=listing.pk)
                submitted = get_object_or_404(listing.revisions.select_for_update(), pk=form.cleaned_data["revision_id"])
                if not submitted.submitted_at or submitted.submitted_at.isoformat() != form.cleaned_data["submitted_version"]:
                    raise ValidationError("This submission changed. Reload before reviewing.")
                reviewed = review_listing_revision(request.user, submitted.pk, form.cleaned_data["decision"], form.cleaned_data["reason"])
                admin.site._registry[ListingRevision].log_change(request, reviewed,
                    f"Listing revision {reviewed.version} {form.cleaned_data['decision']} through custom review. " +
                    ("Reason: " + form.cleaned_data["reason"] if form.cleaned_data["decision"] == "rejected" else ""))
        except ValidationError as error:
            form.add_error(None, error.messages)
        except OSError:
            form.add_error(None, "The submitted photos could not be read. No decision was saved.")
        else:
            messages.success(request, "Listing submission approved." if form.cleaned_data["decision"] == "approved" else "Listing submission rejected. Previous published content is preserved.")
            return redirect("accounts:admin_listing_details", pk=listing.pk)
    can_photos = can_view(request, RoomImage)
    identity_status = OwnerVerification.objects.filter(user=listing.owner).values_list("status", flat=True).first()
    can_owner_profile = (request.user.has_perm("accounts.view_user") and not listing.owner.is_staff
        and not listing.owner.is_superuser and listing.owner.role in User.Role.values)
    from listings.services import DRAFT_FIELDS
    published = listing.published_revision
    published_fields = []
    if published:
        for name in DRAFT_FIELDS:
            value = getattr(published, name)
            if name in ("room_type", "furnishing"):
                value = getattr(published, "get_" + name + "_display")()
            if isinstance(value, bool):
                value = "Allowed" if value else "Not allowed"
            published_fields.append((published._meta.get_field(name).verbose_name, value))
    # Availability moderation stays disabled; approval never substitutes for deactivation.
    return render(request, "custom_admin/listing_details.html", {
        "listing": listing, "revision": revision, "pending_revision": pending_revision,
        "review_form": form, "can_review": can_review, "published_revision": published,
        "published_fields": published_fields,
        "published_photos": list(published.photos.all()) if published and can_photos else [],
        "photos": list(revision.photos.all()) if revision and can_photos else [],
        "can_photos": can_photos, "can_owner_profile": can_owner_profile,
        "owner_identity_status": dict(OwnerVerification.Status.choices).get(identity_status, "Not submitted"),
        "owner_identity_verified": identity_status == "approved",
        "owner_email_verified": email_is_verified(listing.owner),
        "last_updated": max(listing.updated_at, revision.updated_at) if revision else listing.updated_at,
        "location_point": {"latitude": float(revision.latitude), "longitude": float(revision.longitude)} if revision else None,
    })
