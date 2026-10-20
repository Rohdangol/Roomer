from mimetypes import guess_type

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from listings.models import ListingRevision, RoomImage, RoomListing
from listings.services import published_listings
from rentals.models import RentalAgreement
from .models import OwnerVerification, TenantIdentityAttempt, User


def require_staff(user):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        raise PermissionDenied("This page is available to active admin staff only.")


def can_view(request, model):
    # Use the registered ModelAdmin policy, including its custom permission overrides.
    model_admin = admin.site._registry.get(model)
    return bool(model_admin and model_admin.has_view_or_change_permission(request))


@login_required(login_url="accounts:login")
@require_GET
def dashboard(request):
    require_staff(request.user)
    can_users = can_view(request, User)
    can_listings = can_view(request, RoomListing)
    can_revisions = can_view(request, ListingRevision)
    can_photos = can_view(request, RoomImage) and can_listings and can_revisions
    pending = []
    review_links = []
    pending_count = 0
    allowed_identity_types = 0
    for model, role in ((OwnerVerification, "Owner"), (TenantIdentityAttempt, "Tenant")):
        if not can_view(request, model):
            continue
        allowed_identity_types += 1
        submissions = model.objects.filter(status="pending").select_related("user").order_by("-submitted_at", "-pk")
        pending_count += submissions.count()
        model_name = model._meta.model_name
        review_links.append({"label": role + " submissions", "url": reverse("accounts:admin_verifications") + "?status=pending&role=" + role.lower()})
        for submission in submissions[:2]:
            pending.append({"user": submission.user, "role": role, "submitted_at": submission.submitted_at,
                "pk": submission.pk, "kind": model_name,
                "url": reverse("accounts:admin_verification_review", args=[role.lower(), submission.pk])})
    # Merge the two real submission types with deterministic ordering across tied dates.
    pending.sort(key=lambda item: (item["submitted_at"], item["kind"], item["pk"]), reverse=True)
    listings = []
    if can_listings and can_revisions:
        listings = RoomListing.objects.select_related("owner").prefetch_related(Prefetch(
            "revisions", queryset=ListingRevision.objects.order_by("-version").prefetch_related("photos"),
            to_attr="dashboard_revisions",
        )).order_by("-created_at", "-pk")[:3]
    return render(request, "custom_admin/dashboard.html", {
        "can_agreements": request.user.has_perm("rentals.view_rentalagreement"),
        "active_rentals": RentalAgreement.objects.filter(status="active").count() if request.user.has_perm("rentals.view_rentalagreement") else None,
        "recent_agreements": RentalAgreement.objects.select_related("current_terms").order_by("-created_at", "-pk")[:3] if request.user.has_perm("rentals.view_rentalagreement") else [],
        "total_users": User.objects.count() if can_users else None,
        "active_listings": published_listings().count() if can_listings else None,
        "pending_count": pending_count if allowed_identity_types == 2 else None,
        "pending_submissions": pending[:2], "review_links": review_links,
        "can_review": bool(allowed_identity_types), "can_users": can_users,
        "can_listings": can_listings, "can_listing_details": can_listings and can_revisions,
        "can_photos": can_photos, "recent_listings": listings,
    })


def private_photo(field):
    if not field:
        raise Http404
    try:
        stream = field.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404
    response = FileResponse(stream, content_type=guess_type(field.name)[0] or "application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required(login_url="accounts:login")
@require_GET
def listing_photo(request, pk):
    require_staff(request.user)
    if not all(can_view(request, model) for model in (RoomListing, ListingRevision, RoomImage)):
        raise PermissionDenied
    # Staff use their own permission-checked endpoint, never an Owner or public file URL.
    photo = get_object_or_404(RoomImage, pk=pk)
    return private_photo(photo.image)


@login_required(login_url="accounts:login")
@require_GET
def profile_photo(request, pk):
    require_staff(request.user)
    # A profile photo is allowed only for a currently visible pending identity submission.
    allowed = any(can_view(request, model) and model.objects.filter(user_id=pk, status="pending").exists()
        for model in (OwnerVerification, TenantIdentityAttempt))
    if not allowed:
        raise Http404
    return private_photo(get_object_or_404(User, pk=pk).profile_picture)
