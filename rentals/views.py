from mimetypes import guess_type

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Exists, OuterRef
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.permissions import owner_needs_verification
from listings.services import published_listings, require_owner, tenant_readable_listings
from listings.models import RoomImage
from .forms import ConfirmActionForm, RentalRequestForm
from .models import RentalRequest
from .services import decide_request, require_tenant, submit_request


def request_access(request, owner):
    if owner:
        require_owner(request.user)
        if owner_needs_verification(request.user):
            return redirect("accounts:verification")
    else:
        require_tenant(request.user)


def scoped_requests(user, owner):
    # Every list and detail starts with participant scope, including historical records.
    records = RentalRequest.objects.filter(listing__owner=user) if owner else RentalRequest.objects.filter(tenant=user)
    return records.select_related("tenant", "listing__owner", "listing_revision").prefetch_related("listing_revision__photos")


def paginated_statuses(request, records, choices, per_page=6):
    status = request.GET.get("status", "all")
    if status not in {"all", *(value for value, label in choices)}:
        raise Http404("Unknown status filter.")
    counts = dict(records.values("status").annotate(total=Count("pk")).values_list("status", "total"))
    filters = [{"value": "all", "label": "All", "count": sum(counts.values())}]
    filters += [{"value": value, "label": label, "count": counts.get(value, 0)} for value, label in choices]
    page = Paginator(records if status == "all" else records.filter(status=status), per_page).get_page(request.GET.get("page"))
    return {"status": status, "status_filters": filters, "page_obj": page}


@login_required(login_url="accounts:login")
@require_GET
def request_list(request, owner=False):
    response = request_access(request, owner)
    if response:
        return response
    records = scoped_requests(request.user, owner)
    if owner:
        from accounts.models import TenantIdentityAttempt
        # Identity approval is distinct from email verification; return only the badge flag.
        records = records.annotate(tenant_identity_verified=Exists(TenantIdentityAttempt.objects.filter(
            user_id=OuterRef("tenant_id"), status="approved")))
    context = paginated_statuses(request, records, RentalRequest.Status.choices[:3])
    # All includes cancelled records even though the wireframe has no separate Cancelled tab.
    context["status_filters"][0]["count"] = records.count()
    context.update({"owner_view": owner, "list_url": reverse("accounts:owner_requests" if owner else "accounts:my_requests")})
    return render(request, "accounts/owner_requests.html" if owner else "accounts/my_requests.html", context)


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def request_create(request, pk):
    require_tenant(request.user)
    listing = get_object_or_404(published_listings(), pk=pk)
    form = RentalRequestForm(request.POST if request.method == "POST" else None, listing=listing)
    if request.method == "POST" and form.is_valid():
        try:
            application = submit_request(request.user, listing.pk, **{name: form.cleaned_data[name]
                for name in ("preferred_move_in", "total_occupancy", "message")})
        except ValidationError as error:
            form.add_error(None, error.messages)
        except IntegrityError:
            form.add_error(None, "A pending or accepted request already exists. Reload My Requests.")
        else:
            messages.success(request, "Your rental request has been sent.")
            return redirect("accounts:request_details", pk=application.pk)
    # The modal and standalone fallback share the exact same validation/service path.
    template = "accounts/_request_form.html" if request.headers.get("X-Requested-With") == "XMLHttpRequest" else "accounts/request_create.html"
    return render(request, template, {"form": form, "listing": listing, "revision": listing.published_revision})


@login_required(login_url="accounts:login")
@require_GET
def request_detail(request, pk, owner=False):
    response = request_access(request, owner)
    if response:
        return response
    application = get_object_or_404(scoped_requests(request.user, owner), pk=pk)
    context = {"application": application, "revision": application.listing_revision, "owner_view": owner}
    if owner:
        from accounts.models import TenantIdentityAttempt
        context["tenant_verified"] = TenantIdentityAttempt.objects.filter(
            user_id=application.tenant_id, status="approved").exists()
    else:
        from accounts.models import OwnerVerification
        # Historical request terms remain visible, but View Room requires current eligibility.
        context["can_view_room"] = tenant_readable_listings(request.user).filter(pk=application.listing_id).exists()
        context["owner_verified"] = OwnerVerification.objects.filter(
            user_id=application.listing.owner_id, status=OwnerVerification.Status.APPROVED).exists()
    return render(request, "accounts/owner_request_details.html" if owner else "accounts/request_details.html", context)


@login_required(login_url="accounts:login")
@require_POST
def request_action(request, pk, action, owner=False):
    response = request_access(request, owner)
    if response:
        return response
    application = get_object_or_404(scoped_requests(request.user, owner), pk=pk)
    form = ConfirmActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Confirm the action before submitting.")
    else:
        try:
            updated = decide_request(request.user, application.pk, action)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Rental request updated.")
            if owner and action == "accept":
                return redirect("accounts:owner_agreement_details", pk=updated.agreement.pk)
    return redirect("accounts:owner_request_details" if owner else "accounts:request_details", pk=pk)


@login_required(login_url="accounts:login")
@require_GET
def rental_photo(request, kind, pk, photo_id):
    from .agreement_services import scoped_agreements
    if request.user.is_staff:
        if not request.user.is_active or not request.user.has_perm("listings.view_roomimage"):
            raise PermissionDenied
    if kind == "agreement":
        agreement = get_object_or_404(scoped_agreements(request.user), pk=pk)
        versions = agreement.versions.all()
        if not request.user.is_staff and request.user.role == "tenant":
            versions = versions.filter(sent_at__isnull=False)
        photo = get_object_or_404(RoomImage, pk=photo_id, revision_id__in=versions.values("listing_revision_id"))
    elif kind == "request":
        if request.user.is_staff:
            if not request.user.has_perm("rentals.view_rentalrequest"):
                raise PermissionDenied
            records = RentalRequest.objects.all()
        else:
            response = request_access(request, request.user.role == "owner")
            if response:
                return response
            records = scoped_requests(request.user, request.user.role == "owner")
        application = get_object_or_404(records, pk=pk)
        photo = get_object_or_404(RoomImage, pk=photo_id, revision_id=application.listing_revision_id)
    else:
        raise Http404
    # The participant lookup precedes file access. Historical photos never use public media paths.
    try:
        stream = photo.image.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404
    response = FileResponse(stream, content_type=guess_type(photo.image.name)[0] or "application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
