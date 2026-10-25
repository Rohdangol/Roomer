from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.urls import reverse

from preferences.models import TenantPreference
from .search_location import selected_location, signed_place


def complete_preference(user):
    preference = TenantPreference.objects.filter(tenant=user).first()
    if preference is None:
        return None
    try:
        # A row alone is insufficient: required factors must be valid; optional coordinates must be paired and valid.
        preference.full_clean()
    except ValidationError:
        return None
    return preference


def preference_search_url(preference, query="", area="", city="", selection=None):
    # Location is the only Home override; the other factors always come from
    # the saved profile, regardless of whether the area matches that profile.
    location = query.strip() or area.strip() or preference.preferred_location
    parameters = {"q": location, "resolve": "1", "radius": "2",
                  "max_budget": str(preference.maximum_budget),
                  "room_type": preference.preferred_room_type,
                  "furnishing": "" if preference.preferred_furnishing == "any" else preference.preferred_furnishing,
                  "amenities": list(preference.amenity_links.values_list("amenity_id", flat=True))}
    if area:
        parameters["area"] = area
    if city:
        parameters["city"] = city
    if not (query.strip() or area.strip() or city.strip()) and preference.latitude is not None and preference.longitude is not None:
        # Navbar entry uses the saved point, not an empty GET value or another
        # provider hit for the same name. Bind it just like an autocomplete choice.
        parameters.update(signed_place({"label": location, "latitude": preference.latitude,
            "longitude": preference.longitude}))
    elif not (query.strip() or area.strip() or city.strip()):
        parameters["setup_location"] = "1"
    if selection:
        if selected_location(selection) and selection.get("point_location", "").strip() == location:
            for name in ("latitude", "longitude", "point_location", "resolved_label", "location_token", "point_source"):
                parameters[name] = selection.get(name, "")
        if selection.get("radius"):
            parameters["radius"] = selection["radius"]
    # A different Home location never inherits the saved area's coordinates.
    return reverse("accounts:find_rooms") + "?" + urlencode(parameters, doseq=True)
