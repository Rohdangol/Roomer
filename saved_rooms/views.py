from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import Resolver404, resolve, reverse
from django.views.decorators.http import require_GET, require_POST

from listings.services import tenant_readable_listings
from rentals.models import AgreementTerms
from .models import SavedRoom
from .services import remove_saved_room, require_tenant, save_room


def return_destination(value):
    # Accept only implemented tenant listing pages, never external or arbitrary redirects.
    parts = urlsplit(value)
    if not parts.scheme and not parts.netloc:
        try:
            destination = resolve(parts.path)
            if destination.view_name in {"accounts:tenant", "accounts:find_rooms", "accounts:room_details", "accounts:saved_rooms"}:
                return parts.path + ("?" + parts.query if parts.query else "")
        except Resolver404:
            pass
    return reverse("accounts:saved_rooms")


@login_required(login_url="accounts:login")
@require_GET
def saved_rooms(request):
    require_tenant(request.user)
    records = SavedRoom.objects.filter(tenant=request.user).select_related("listing__owner", "listing__published_revision")
    page = Paginator(records, 6).get_page(request.GET.get("page"))
    ids = [record.listing_id for record in page]
    visible = {room.pk: room for room in tenant_readable_listings(request.user).filter(pk__in=ids).prefetch_related("published_revision__photos")}
    # The actor's sent agreement is an independent authorization to retained terms,
    # not permission to expose the listing's current hidden revision.
    historical = {}
    for terms in AgreementTerms.objects.filter(agreement__tenant=request.user,
            agreement__listing_id__in=ids, sent_at__isnull=False).select_related("agreement").prefetch_related(
            "listing_revision__photos").order_by("-agreement__created_at", "-version"):
        historical.setdefault(terms.agreement.listing_id, terms)
    entries = []
    for record in page:
        room = visible.get(record.listing_id)
        entry = {"listing_id": record.listing_id, "save_target": {"pk": record.listing_id, "is_saved": True},
            "status": "Unavailable / restricted", "can_request": False}
        if room is not None:
            revision = room.published_revision
            photo = next(iter(revision.photos.all()), None)
            entry.update(title=revision.title, location=revision.location_display, rent=revision.monthly_rent,
                photo_url=reverse("accounts:tenant_photo", args=[photo.pk]) if photo else "",
                detail_url=reverse("accounts:room_details", args=[room.pk]),
                status=room.get_listing_status_display(), can_request=room.listing_status == "available")
        else:
            hidden = record.listing
            # Explain the safe availability category without returning hidden content.
            if hidden.archive_source != "admin" and hidden.owner.is_active:
                if hidden.archived_at or hidden.listing_status == "inactive":
                    entry["status"] = "Inactive / unpublished"
                elif not hidden.published_revision_id:
                    entry["status"] = "Unpublished"
            terms = historical.get(record.listing_id)
            if terms:
                snapshot = terms.listing_snapshot
                photo = next(iter(terms.listing_revision.photos.all()), None)
                entry.update(title=snapshot.get("title", "Agreement room"),
                    location=", ".join(value for value in (snapshot.get("locality"), snapshot.get("city")) if value),
                    rent=terms.monthly_rent, historical=True,
                    photo_url=reverse("accounts:rental_photo", args=["agreement", terms.agreement_id, photo.pk]) if photo else "",
                    agreement_url=reverse("accounts:agreement_details", args=[terms.agreement_id]))
        entries.append(entry)
    return render(request, "accounts/saved_rooms.html", {"page_obj": page, "entries": entries, "page_numbers": page.paginator.get_elided_page_range(page.number)})


@login_required(login_url="accounts:login")
@require_POST
def change_saved_room(request, pk):
    require_tenant(request.user)
    action = request.POST.get("action")
    if action == "save":
        created = save_room(request.user, pk)
        messages.success(request, "Room saved." if created else "Room is already saved.")
    elif action == "remove":
        remove_saved_room(request.user, pk)
        messages.success(request, "Room removed from Saved Rooms.")
    else:
        return HttpResponseBadRequest("Choose save or remove.")
    try:
        destination = return_destination(request.POST.get("return_to", ""))
    except ValueError:
        destination = reverse("accounts:saved_rooms")
    return redirect(destination)
