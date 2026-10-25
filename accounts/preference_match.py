"""Room Details uses the same scorer and validated inputs as recommendation cards."""
from django.core import signing
from django.http import QueryDict

from preferences.recommendations import (preferences_from_filters, score_room,
    recommendation_candidates, saved_preference_boundary, valid_boundary)
from .preference_onboarding import complete_preference
from .room_search import RoomSearchForm
from .search_location import selected_location, signed_place


def room_preference_match(tenant, revision, parameters):
    token = parameters.get("match_context")
    search_fields = {"q", "area", "city", "max_budget", "room_type", "furnishing", "amenities", "latitude", "longitude"}
    from_search = any(parameters.get(name) for name in search_fields)
    if token or from_search:
        inputs = parameters
        if token:
            try:
                snapshot = signing.loads(token, salt="roomer.preference-match")
                if snapshot["tenant"] != tenant.pk:
                    raise ValueError
                inputs = QueryDict(mutable=True)
                for name, value in snapshot["filters"].items():
                    inputs.setlist(name, [str(item) for item in value] if isinstance(value, list) else [str(value)])
            except (signing.BadSignature, ValueError, KeyError, TypeError):
                return {}
        form = RoomSearchForm(inputs)
        if not form.is_valid() or (not token and any(inputs.get(name) for name in ("q", "area", "city", "latitude", "longitude")) and not selected_location(inputs)):
            return {}
        boundary = {name: form.cleaned_data.get(name) for name in ("latitude", "longitude", "radius")}
        preference, amenity_ids = preferences_from_filters(form.cleaned_data)
        source = "Based on saved preferences" if token and snapshot.get("source") == "saved" else "Based on your search preferences"
        # Keep only validated search inputs in the return URL. Home snapshots can
        # resolve their saved text on entry; Find Rooms keeps its selected point.
        original = RoomSearchForm(parameters)
        use_original = from_search and original.is_valid() and (
            not any(parameters.get(name) for name in ("q", "area", "city", "latitude", "longitude")) or selected_location(parameters))
        return_inputs = parameters if use_original else inputs
        query = QueryDict(mutable=True)
        for name in form.fields:
            if return_inputs.get(name):
                query.setlist(name, return_inputs.getlist(name))
        if query.get("q") and not query.get("latitude"):
            query["resolve"] = "1"
        elif query.get("latitude") and not selected_location(query):
            # The boundary has already been validated from our signed snapshot;
            # bind its point for return navigation without another provider lookup.
            for name, value in signed_place({"label": query.get("q", ""),
                    "latitude": float(query["latitude"]), "longitude": float(query["longitude"])}).items():
                query[name] = value
        if parameters.get("page", "").isdecimal() and len(parameters["page"]) <= 9:
            query["page"] = parameters["page"]
        search_query = query.urlencode()
    else:
        preference = complete_preference(tenant)
        if preference is None:
            return {}
        boundary = saved_preference_boundary(preference)
        amenity_ids = set(preference.amenity_links.values_list("amenity_id", flat=True))
        source = "Based on saved preferences"
        search_query = ""
    if not valid_boundary(boundary):
        return {}
    distance = recommendation_candidates(tenant, boundary).filter(
        published_revision_id=revision.pk).values_list("distance_km", flat=True).first()
    result = score_room(preference, revision, amenity_ids,
        {link.amenity_id for link in revision.amenity_links.all()}, distance_km=distance,
        radius=boundary.get("radius") or 2)
    if result is None:
        return {}  # Outside the boundary: keep normal room details, without match UI.
    return {"result": result, "source": source, "search_query": search_query}
