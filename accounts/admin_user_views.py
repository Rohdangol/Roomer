from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from urllib.parse import urlencode

from .admin_dashboard_views import can_view, private_photo, require_staff
from .models import OwnerVerification, TenantIdentityAttempt, User
from .verification_services import email_is_verified


def require_user_view(request):
    require_staff(request.user)
    if not request.user.has_perm("accounts.view_user"):
        raise PermissionDenied("User-view permission is required.")


def ordinary_users():
    # Staff/superusers are outside this Tenant/Owner directory, including its photos.
    return User.objects.filter(role__in=User.Role.values, is_staff=False, is_superuser=False)


@login_required(login_url="accounts:login")
@require_GET
def users(request):
    require_user_view(request)
    role = request.GET.get("role", "all")
    if role not in User.Role.values:
        role = "all"
    query = request.GET.get("q", "").strip()[:254]
    records = ordinary_users()
    has_users = records.exists()
    if role != "all":
        records = records.filter(role=role)
    if query:
        records = records.filter(Q(full_name__icontains=query) | Q(email__icontains=query))
    # Fetch status only, never identity document fields or file URLs.
    records = records.annotate(
        owner_identity_status=Subquery(OwnerVerification.objects.filter(user_id=OuterRef("pk")).values("status")[:1]),
        tenant_identity_status=Subquery(TenantIdentityAttempt.objects.filter(user_id=OuterRef("pk"))
            .order_by("-submitted_at", "-pk").values("status")[:1]),
    ).order_by("-date_joined", "-pk")
    page = Paginator(records, 3).get_page(request.GET.get("page"))
    for person in page:
        person.registration_email_verified = email_is_verified(person)
        status = person.owner_identity_status if person.role == User.Role.OWNER else person.tenant_identity_status
        person.identity_status_label = {"approved": "Approved", "pending": "Pending review",
            "rejected": "Rejected"}.get(status, "Not submitted")
    return render(request, "custom_admin/users.html", {
        "page_obj": page, "role": role, "query": query, "has_users": has_users,
        "role_filters": [("all", "All"), ("tenant", "Tenants"), ("owner", "Owners")],
        "pagination_query": urlencode({"role": role, "q": query}),
        "page_numbers": page.paginator.get_elided_page_range(page.number),
    })


@login_required(login_url="accounts:login")
@require_GET
def profile_photo(request, pk):
    require_user_view(request)
    person = get_object_or_404(ordinary_users(), pk=pk)
    return private_photo(person.profile_picture)


@login_required(login_url="accounts:login")
@require_GET
def user_details(request, pk):
    from listings.models import ListingRevision, RoomListing
    from preferences.models import TenantPreference
    from saved_rooms.models import SavedRoom

    require_user_view(request)
    person = get_object_or_404(ordinary_users(), pk=pk)
    model = OwnerVerification if person.role == User.Role.OWNER else TenantIdentityAttempt
    # Read display metadata only; private document fields are never loaded into this page.
    identity = model.objects.filter(user=person).order_by("-submitted_at", "-pk").values(
        "pk", "status", "document_type", "reviewed_at").first()
    review_url = None
    if identity:
        identity["status_label"] = dict(OwnerVerification.Status.choices).get(identity["status"], "Unavailable")
        identity["document_type_label"] = dict(OwnerVerification.DocumentType.choices).get(identity["document_type"], "Unavailable")
        if can_view(request, model):
            review_url = reverse(f"admin:accounts_{model._meta.model_name}_change", args=[identity["pk"]])
    overview = {"saved_room_count": None}
    if person.role == User.Role.OWNER:
        if can_view(request, RoomListing):
            listings = RoomListing.objects.filter(owner=person)
            overview = {"total_listings": listings.count(), "active_listings": listings.filter(
                archived_at__isnull=True, listing_status="available", published_revision__approval_status="approved").count(),
                "listings_url": (reverse("accounts:admin_listings") + "?owner=" + str(person.pk))
                    if can_view(request, ListingRevision) else None, "can_listing_counts": True}
    else:
        if can_view(request, TenantPreference):
            overview["preference"] = TenantPreference.objects.filter(tenant=person).first()
            overview["can_preferences"] = True
        # Saved rooms are private account activity; require their own model-view permission.
        if request.user.has_perm("saved_rooms.view_savedroom"):
            overview["saved_room_count"] = SavedRoom.objects.filter(tenant=person).count()
    from rentals.models import RentalAgreement, RentalRequest
    overview["pending_requests"] = None
    overview["active_rentals"] = None
    if request.user.has_perm("rentals.view_rentalrequest"):
        records = RentalRequest.objects.filter(listing__owner=person) if person.role == "owner" else RentalRequest.objects.filter(tenant=person)
        overview["pending_requests"] = records.filter(status="pending").count()
    if request.user.has_perm("rentals.view_rentalagreement"):
        agreements = RentalAgreement.objects.filter(owner=person) if person.role == "owner" else RentalAgreement.objects.filter(tenant=person)
        overview["active_rentals"] = agreements.filter(status="active").count()
    return render(request, "custom_admin/user_details.html", {
        "person": person, "identity": identity, "review_url": review_url,
        "email_verified": email_is_verified(person), "overview": overview,
        "can_change_status": request.user.has_perm("accounts.change_user") and person.pk != request.user.pk,
    })


@login_required(login_url="accounts:login")
@require_POST
def change_account_status(request, pk):
    require_user_view(request)
    if not request.user.has_perm("accounts.change_user") or pk == request.user.pk:
        raise PermissionDenied("Permission to change another ordinary account is required.")
    with transaction.atomic():
        # Lock and recheck the target before changing only its independent account flag.
        person = get_object_or_404(ordinary_users().select_for_update(), pk=pk)
        if person.is_staff or person.is_superuser or person.pk == request.user.pk:
            raise PermissionDenied("Staff, superuser and self changes are not allowed here.")
        action = request.POST.get("action")
        if request.POST.get("confirm") != "yes":
            messages.error(request, "Confirm the account status change before submitting.")
        elif action not in ("suspend", "reactivate"):
            messages.error(request, "Choose a supported account action.")
        elif person.is_active == (action == "reactivate"):
            messages.warning(request, "The account status has already changed. Review its current status.")
        else:
            previous = person.is_active
            person.is_active = action == "reactivate"
            person.save(update_fields=["is_active"])
            # Reuse Django admin LogEntry: actor, target and action commit with the status change.
            admin.site._registry[User].log_change(request, person,
                f"{'Reactivated' if person.is_active else 'Suspended'} account from User Details; is_active: {previous} -> {person.is_active}.")
            messages.success(request, "Account reactivated." if person.is_active else "Account suspended.")
    return redirect("accounts:admin_user_details", pk=pk)
