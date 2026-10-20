from mimetypes import guess_type
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_http_methods
from preferences.models import TenantPreference
from preferences.services import save_tenant_preference
from .profile_forms import TextOnlyPreferenceForm
from .preference_onboarding import complete_preference, preference_search_url

from listings.models import RoomImage
from listings.services import published_listings
from .models import OwnerVerification, User
from .room_search import RoomSearchForm, search_rooms


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def home(request):
    if request.user.is_staff or request.user.role != User.Role.TENANT:
        return HttpResponseForbidden("This page is available to tenants only.")
    query = request.GET.get("q", "").strip()[:255]
    area = request.GET.get("area", "").strip()[:100]
    city = request.GET.get("city", "").strip()[:100]
    preference = complete_preference(request.user)
    search_requested = "search" in request.GET or "q" in request.GET or "area" in request.GET
    if request.method == "GET" and search_requested and preference:
        return redirect(preference_search_url(preference, query, area, city))
    show_preferences = request.method == "POST" or (search_requested and preference is None)
    form = TextOnlyPreferenceForm(request.POST if request.method == "POST" else None,
        instance=TenantPreference(tenant=request.user),
        initial={"preferred_location": query or area, "preferred_furnishing": "any"})
    if request.method == "POST" and form.is_valid():
        fields = ("preferred_location", "latitude", "longitude", "maximum_budget", "preferred_room_type", "preferred_furnishing")
        try:
            preference = save_tenant_preference(request.user, {name: form.cleaned_data[name] for name in fields},
                amenity_ids=[item.pk for item in form.cleaned_data["amenities"]])
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            return redirect(preference_search_url(preference))
    eligible = published_listings()
    rooms = search_rooms({"q": query, "area": area, "city": city}, tenant=request.user)
    # No matching algorithm is agreed yet: this fallback is explicitly newest-first.
    latest_rooms = list(rooms[:3])
    # Area shortcuts need a real area; listings without one remain in normal city/address search.
    neighbourhoods = list(eligible.exclude(published_revision__locality="").values("published_revision__city", "published_revision__locality").annotate(room_count=Count("pk")).order_by("-room_count", "published_revision__locality", "published_revision__city")[:4])
    return render(request, "accounts/tenant_home.html", {
        "show_preferences": show_preferences, "onboarding_form": form,
        "page_title": "Tenant Home", "query": query, "area": area, "city": city,
        "latest_rooms": latest_rooms, "fresh_rooms": latest_rooms[:2],
        "neighbourhoods": neighbourhoods, "has_filter": bool(query or area or city),
    })


@login_required(login_url="accounts:login")
def listing_photo(request, pk):
    if request.user.is_staff or request.user.role != User.Role.TENANT:
        return HttpResponseForbidden("This page is available to tenants only.")
    # A known file ID is insufficient: only the current eligible published version may be served.
    photo = RoomImage.objects.filter(pk=pk, revision__published_for_listings__in=published_listings()).first()
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
def find_rooms(request):
    if request.user.is_staff or request.user.role != User.Role.TENANT:
        return HttpResponseForbidden("This page is available to tenants only.")
    parameters = request.GET.copy()
    if not parameters.get("radius"):
        parameters["radius"] = "2"
    form = RoomSearchForm(parameters)
    # Invalid filters must not silently broaden the search.
    rooms = search_rooms(form.cleaned_data, tenant=request.user) if form.is_valid() else published_listings().none()
    page = Paginator(rooms, 4).get_page(request.GET.get("page"))
    parameters.pop("page", None)
    return render(request, "accounts/find_rooms.html", {
        "page_title": "Find Rooms", "form": form, "page_obj": page,
        "page_numbers": page.paginator.get_elided_page_range(page.number),
        "pagination_query": parameters.urlencode(),
    })


@login_required(login_url="accounts:login")
def room_details(request, pk):
    if request.user.is_staff or request.user.role != User.Role.TENANT:
        return HttpResponseForbidden("This page is available to tenants only.")
    # Resolve the stable listing only through eligibility; never accept a revision ID.
    listing = get_object_or_404(search_rooms({}, tenant=request.user).select_related("owner"), pk=pk)
    revision = listing.published_revision
    point = None
    similar = []
    nearby_query = ""
    if revision.latitude is not None and revision.longitude is not None:
        point = {"latitude": float(revision.latitude), "longitude": float(revision.longitude)}
        filters = {**point, "radius": 2}
        similar = list(search_rooms(filters, tenant=request.user).exclude(pk=listing.pk)[:3])
        nearby_query = urlencode(filters)
    return render(request, "accounts/room_details.html", {
        "listing": listing, "revision": revision, "photos": list(revision.photos.all()),
        "owner_name": listing.owner.full_name.strip() or "Room Owner",
        "owner_verified": OwnerVerification.objects.filter(user_id=listing.owner_id, status="approved").exists(),
        "location_point": point, "similar_rooms": similar, "nearby_query": nearby_query,
        "search_query": request.GET.urlencode(),
    })
