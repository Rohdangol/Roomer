from mimetypes import guess_type
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_http_methods
from preferences.models import TenantPreference
from preferences.services import save_tenant_preference
from preferences.recommendations import recommend_rooms
from .profile_forms import TextOnlyPreferenceForm
from .preference_onboarding import complete_preference, preference_search_url

from listings.models import RoomImage
from listings.services import published_listings, tenant_readable_listings
from .models import OwnerVerification, User
from .room_search import RoomSearchForm, search_rooms
from .neighbourhoods import available_neighbourhoods
from .search_location import resolve_search_location, selected_location
from .preference_match import room_preference_match


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
    location_parameters = request.POST.copy() if request.method == "POST" else request.GET.copy()
    if request.method == "POST":
        location_parameters["q"] = request.POST.get("preferred_location", "").strip()
    location_parameters.setdefault("radius", "2")
    location_context = {"location_choices": [], "location_lookup_message": "", "location_required": False}
    location_ok = True
    if search_requested or request.method == "POST":
        location_form = RoomSearchForm(location_parameters)
        location_ok = location_form.is_valid()
        if location_ok:
            location_context = resolve_search_location(location_parameters)
            location_ok = not location_context["location_required"]
        else:
            location_context["location_lookup_message"] = "Choose a location from the suggestions."
        if request.method == "GET" and location_ok:
            query = location_parameters.get("q", query)
    if request.method == "GET" and search_requested and "q" in request.GET and not query and not area:
        location_ok = False
        location_context["location_lookup_message"] = "Choose a location from the suggestions."
    if request.method == "GET" and search_requested and preference and location_ok:
        return redirect(preference_search_url(preference, query, area, city, selection=location_parameters))
    show_preferences = request.method == "POST" or (search_requested and preference is None and location_ok)
    form = TextOnlyPreferenceForm(request.POST if request.method == "POST" else None,
        instance=TenantPreference(tenant=request.user),
        initial={**{name: location_parameters.get(name, "") for name in ("latitude", "longitude", "point_location", "resolved_label", "location_token", "point_source")}, "preferred_location": query or area, "preferred_furnishing": "any"})
    if request.method == "POST" and not location_ok:
        form.add_error("preferred_location", "Choose a location from the suggestions.")
    if request.method == "POST" and form.is_valid():
        fields = ("preferred_location", "latitude", "longitude", "maximum_budget", "preferred_room_type", "preferred_furnishing")
        try:
            preference = save_tenant_preference(request.user, {name: form.cleaned_data[name] for name in fields},
                amenity_ids=[item.pk for item in form.cleaned_data["amenities"]],
                coordinates_selected=form.cleaned_data["coordinates_selected"])
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            return redirect(preference_search_url(preference, selection=location_parameters))
    eligible = tenant_readable_listings(request.user).filter(listing_status="available")
    rooms = search_rooms({"q": query, "area": area, "city": city}, tenant=request.user)
    # Latest listings belong only to Fresh on Roomer, never personalized results.
    latest_rooms = list(rooms[:3])
    # Area shortcuts need a real area; listings without one remain in normal city/address search.
    all_neighbourhoods = available_neighbourhoods(eligible)
    neighbourhoods = all_neighbourhoods[:3]
    return render(request, "accounts/tenant_home.html", {
        "show_preferences": show_preferences, "onboarding_form": form,
        "selected_location": location_parameters, **location_context,
        "page_title": "Tenant Home", "query": query, "area": area, "city": city,
        "latest_rooms": latest_rooms, "fresh_rooms": latest_rooms[:3],
        "recommendation_preference": preference,
        "recommended_rooms": recommend_rooms(request.user, preference),
        "neighbourhoods": neighbourhoods, "has_filter": bool(query or area or city),
        "all_neighbourhoods": all_neighbourhoods, "show_neighbourhoods": request.GET.get("browse") == "neighbourhoods",
    })


@login_required(login_url="accounts:login")
def listing_photo(request, pk):
    if request.user.is_staff or request.user.role != User.Role.TENANT:
        return HttpResponseForbidden("This page is available to tenants only.")
    # A known file ID is insufficient: only the current eligible published version may be served.
    photo = RoomImage.objects.filter(pk=pk, revision__published_for_listings__in=tenant_readable_listings(request.user)).first()
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
@require_http_methods(["GET", "POST"])
def find_rooms(request):
    if request.user.is_staff or request.user.role != User.Role.TENANT:
        return HttpResponseForbidden("This page is available to tenants only.")
    # Only the navbar opts into saved defaults. Redirect removes the entry flag,
    # so filter edits, pagination and Reset cannot silently reapply preferences.
    if request.GET.get("initial") == "preferences" and request.GET.get("entry") != "fresh":
        preference = complete_preference(request.user)
        if preference:
            return redirect(preference_search_url(preference))
        return redirect("accounts:find_rooms")
    parameters = request.POST.copy() if request.method == "POST" else request.GET.copy()
    setup_location = parameters.get("setup_location") == "1"
    setup_error = ""
    if request.method == "POST":
        point_form = RoomSearchForm(parameters)
        if not setup_location or not point_form.is_valid() or not selected_location(parameters):
            setup_error = "Choose a location from the suggestions or select a map point before saving."
        else:
            from preferences.services import save_preference_location
            try:
                preference = save_preference_location(request.user, parameters["q"],
                    point_form.cleaned_data["latitude"], point_form.cleaned_data["longitude"])
            except ValidationError as error:
                setup_error = " ".join(error.messages)
            else:
                return redirect(preference_search_url(preference))
    if not parameters.get("radius"):
        parameters["radius"] = "2"
    # Only recommendations consume the selected search values and radius.
    location_context = {"location_choices": [], "location_lookup_message": ""}
    if RoomSearchForm(parameters).is_valid():
        location_context = resolve_search_location(parameters)
    form = RoomSearchForm(parameters)
    form.is_valid()
    valid_filters = form.is_valid() and not location_context.get("location_required")
    # The independent catalogue always uses empty filters, with the same public
    # visibility checks and saved-state/photo loading as other Tenant cards.
    rooms = search_rooms({}, tenant=request.user).filter(
        pk__in=tenant_readable_listings(request.user).values("pk"),
    )
    recommendations = recommend_rooms(request.user, limit=6, filters=form.cleaned_data) if valid_filters else []
    page = Paginator(rooms, 4).get_page(request.GET.get("page"))
    parameters.pop("page", None)
    parameters.pop("csrfmiddlewaretoken", None)
    return render(request, "accounts/find_rooms.html", {
        "page_title": "Find Rooms", "form": form, "page_obj": page,
        "recommended_rooms": recommendations,
        "show_recommendations": valid_filters and (
            form.cleaned_data.get("max_budget") is not None or form.cleaned_data.get("latitude") is not None
            or any(form.cleaned_data.get(name) for name in ("q", "area", "city", "room_type", "furnishing", "amenities"))),
        "page_numbers": page.paginator.get_elided_page_range(page.number),
        "pagination_query": parameters.urlencode(),
        "setup_location": setup_location, "setup_error": setup_error,
        **location_context,
    })


@login_required(login_url="accounts:login")
def room_details(request, pk):
    if request.user.is_staff or request.user.role != User.Role.TENANT:
        return HttpResponseForbidden("This page is available to tenants only.")
    # Viewing an approved reserved/occupied room does not authorize a new request.
    from django.db.models import Exists, OuterRef
    from saved_rooms.models import SavedRoom
    readable = tenant_readable_listings(request.user).annotate(
        is_saved=Exists(SavedRoom.objects.filter(tenant=request.user, listing_id=OuterRef("pk"))))
    listing = get_object_or_404(readable, pk=pk)
    revision = listing.published_revision
    preference_match = room_preference_match(request.user, revision, request.GET)
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
        "preference_match": preference_match,
        "owner_name": listing.owner.full_name.strip() or "Room Owner",
        "owner_verified": OwnerVerification.objects.filter(user_id=listing.owner_id, status="approved").exists(),
        "location_point": point, "similar_rooms": similar, "nearby_query": nearby_query,
        "search_query": preference_match.get("search_query", ""),
        "can_request_room": published_listings().filter(pk=listing.pk).exists(),
    })
