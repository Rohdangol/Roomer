from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.urls import reverse

from preferences.models import TenantPreference


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


def preference_search_url(preference, query="", area="", city=""):
    parameters = {"q": query or area or preference.preferred_location,
                  "max_budget": str(preference.maximum_budget),
                  "room_type": preference.preferred_room_type,
                  "furnishing": "" if preference.preferred_furnishing == "any" else preference.preferred_furnishing,
                  "amenities": list(preference.amenity_links.values_list("amenity_id", flat=True))}
    if area:
        parameters["area"] = area
    if city:
        parameters["city"] = city
    # Text location searches do not inherit old coordinates and constrain a new area accidentally.
    return reverse("accounts:find_rooms") + "?" + urlencode(parameters, doseq=True)
