from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import Resolver404, resolve, reverse
from django.views.decorators.http import require_GET, require_POST

from accounts.room_search import search_rooms
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
    records = SavedRoom.objects.filter(tenant=request.user)
    page = Paginator(records, 6).get_page(request.GET.get("page"))
    visible = {room.pk: room for room in search_rooms({}, tenant=request.user).filter(pk__in=[record.listing_id for record in page])}
    entries = [{"listing": visible.get(record.listing_id), "listing_id": record.listing_id} for record in page]
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
