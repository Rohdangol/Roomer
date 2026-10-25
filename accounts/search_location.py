"""Validated search points and explicit choices, independent of saved preferences."""
from django.core import signing
from .listing_geocoding import lookup_text_location
from .neighbourhoods import normalized_location


SELECTION_SALT = "roomer.search-location"


def signed_place(result):
    place = {"q": result.get("display_name", result["label"])[:255],
             "latitude": f'{result["latitude"]:.6f}', "longitude": f'{result["longitude"]:.6f}'}
    place["point_location"] = place["q"]
    place["resolved_label"] = place["q"]
    place["location_token"] = signing.dumps(place, salt=SELECTION_SALT)
    place["point_source"] = "suggestion"
    return place


def selected_location(parameters):
    location = parameters.get("q", "").strip() or parameters.get("area", "").strip() or parameters.get("city", "").strip()
    if not parameters.get("latitude") or not parameters.get("longitude"):
        return False
    if normalized_location(parameters.get("point_location", "")) != normalized_location(location):
        return False
    if parameters.get("point_source") in ("map", "gps"):
        return True  # Explicit manual points are allowed; RoomSearchForm validates bounds.
    try:
        place = signing.loads(parameters.get("location_token", ""), salt=SELECTION_SALT)
        return (place["q"] == location and
                float(place["latitude"]) == float(parameters["latitude"]) and
                float(place["longitude"]) == float(parameters["longitude"]))
    except (signing.BadSignature, ValueError, KeyError, TypeError):
        return False


def resolve_search_location(parameters):
    location = parameters.get("q", "").strip() or parameters.get("area", "").strip() or parameters.get("city", "").strip()
    context = {"location_choices": [], "location_lookup_message": "", "location_required": False}
    if selected_location(parameters) or (not location and not parameters.get("latitude") and not parameters.get("longitude")):
        return context
    old_location = parameters.get("point_location", "")
    if old_location and normalized_location(old_location) != normalized_location(location):
        parameters.pop("area", None)
        parameters.pop("city", None)
    for name in ("latitude", "longitude", "point_location", "resolved_label", "location_token", "point_source"):
        parameters.pop(name, None)
    context["location_required"] = True
    context["location_lookup_message"] = "Choose a location from the suggestions."
    # Only existing saved-text/default and neighbourhood entries may resolve on
    # arrival. Ordinary typed searches must select a suggestion, including without JS.
    if not location or not (parameters.get("resolve") == "1" or parameters.get("area")):
        return context
    data, status = lookup_text_location(location, parameters.get("city", ""))
    results = data.get("results", [])
    results = list({(round(item["latitude"], 6), round(item["longitude"], 6), item["label"]): item for item in results}.values())
    if status != 200 or not results:
        context["location_lookup_message"] = "Nearby search is unavailable. Retry location lookup or select a map point. " + (data.get("error") or "No matching places found.")
    elif len(results) == 1:
        for name, value in signed_place(results[0]).items():
            parameters[name] = value
        context["location_required"] = False
        context["location_lookup_message"] = ""
    else:
        context["location_lookup_message"] = "Choose a matching location below. No radius search runs until a location is selected."
        for result in results:
            selected = parameters.copy()
            selected.pop("page", None)
            for name, value in signed_place(result).items():
                selected[name] = value
            context["location_choices"].append({"label": selected["q"], "query": selected.urlencode()})
    return context
