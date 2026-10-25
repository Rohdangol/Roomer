"""Dynamic room matching using the approved five-factor policy."""
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
import math

from accounts.listing_geocoding import lookup_text_location
from django.core.exceptions import PermissionDenied
from django.core import signing

from listings.services import tenant_readable_listings
from listings.distance import within_radius


WEIGHTS = {"location": Decimal("0.30"), "budget": Decimal("0.30"),
           "amenities": Decimal("0.15"), "room_type": Decimal("0.15"),
           "furnishing": Decimal("0.10")}


def score_room(preference, revision, preferred_amenities, room_amenities, *, distance_km=None, radius=None):
    """Pure calculation; IDs are supplied in sets to avoid per-room queries."""
    if not within_radius(distance_km, radius):
        return None  # An unresolved/outside point must never produce a match score.
    budget = Decimal(preference.maximum_budget) if preference.maximum_budget is not None else None
    rent = Decimal(revision.monthly_rent)
    matched = len(preferred_amenities & room_amenities)
    factors = {
        "location": Decimal(1),
        "budget": Decimal(1) if budget is None or rent <= budget else budget / rent,
        "amenities": Decimal(matched) / len(preferred_amenities) if preferred_amenities else Decimal(1),
        "room_type": Decimal(int(not preference.preferred_room_type or preference.preferred_room_type == revision.room_type)),
        "furnishing": Decimal(int(preference.preferred_furnishing in ("", "any")
                                 or preference.preferred_furnishing == revision.furnishing)),
    }
    score = sum(WEIGHTS[name] * value for name, value in factors.items())
    explanation = ["Within your selected area"]
    if budget is not None:
        explanation.append("Within budget" if rent <= budget else "Above budget")
    if preferred_amenities:
        explanation.append(f"{matched}/{len(preferred_amenities)} preferred amenities")
    if preference.preferred_room_type:
        explanation.append("Room type matches" if factors["room_type"] else "Different room type")
    if preference.preferred_furnishing not in ("", "any"):
        explanation.append("Furnishing matches" if factors["furnishing"] else "Different furnishing")
    breakdown = [
        {"label": "Location", "detail": "Within your selected area"},
        {"label": "Budget", "detail": "No maximum set" if budget is None else ("Within budget" if rent <= budget else "Above budget")},
        {"label": "Amenities", "detail": f"{matched}/{len(preferred_amenities)} match" if preferred_amenities else "No preference"},
        {"label": "Room type", "detail": "Any" if not preference.preferred_room_type else ("Matches" if factors["room_type"] else "Different type")},
        {"label": "Furnishing", "detail": "Any" if preference.preferred_furnishing in ("", "any") else ("Matches" if factors["furnishing"] else "Different furnishing")},
    ]
    for row, factor in zip(breakdown, factors.values()):
        row["percentage"] = int((factor * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return {"score": score, "percentage": int((score * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)),
            "distance_km": float(distance_km), "radius": float(radius), "factors": factors, "breakdown": breakdown, "explanation": " · ".join(explanation)}


def recommendation_candidates(tenant, boundary=None):
    # Readability includes moderation and Owner verification; availability is a
    # separate requirement so reserved/occupied rooms never enter recommendations.
    if not tenant.is_authenticated or not tenant.is_active or tenant.is_staff or tenant.role != "tenant":
        raise PermissionDenied("An active Tenant account is required.")
    from accounts.room_search import search_rooms

    return search_rooms(boundary or {}, tenant=tenant).filter(
        pk__in=tenant_readable_listings(tenant).values("pk"),
    )


def recommend_rooms(tenant, preference=None, limit=3, filters=None):
    boundary = {}
    if filters is not None:
        # Only map coordinates/radius constrain the pool; all other search values
        # influence ranking; Find Rooms keeps an independent unfiltered catalogue.
        boundary = {name: filters.get(name) for name in ("latitude", "longitude", "radius")}
        preference, preferred = preferences_from_filters(filters)
        location = preference.preferred_location
        if not (location or preference.maximum_budget is not None or preference.preferred_room_type
                or preference.preferred_furnishing or preferred or boundary.get("latitude") is not None):
            return []
    elif preference is None:
        return []
    else:
        preferred = set(preference.amenity_links.values_list("amenity_id", flat=True))
        boundary = saved_preference_boundary(preference)
    if not valid_boundary(boundary):
        return []
    rooms = list(recommendation_candidates(tenant, boundary))
    context = recommendation_context(tenant, preference, preferred, boundary=boundary, source="search" if filters is not None else "saved")
    for listing in rooms:
        revision = listing.published_revision
        listing.recommendation = score_room(preference, revision, preferred,
            {link.amenity_id for link in revision.amenity_links.all()},
            distance_km=listing.distance_km, radius=boundary.get("radius") or 2)
        listing.recommendation["context"] = context
    # Python sorting is stable: equal scores retain the query's newest-publication,
    # then largest-ID order. Display rounding must not change ranking.
    rooms.sort(key=lambda room: room.recommendation["score"], reverse=True)
    return rooms[:limit]


def preferences_from_filters(filters):
    preference = SimpleNamespace(preferred_location=filters.get("q") or filters.get("area") or filters.get("city") or "",
        maximum_budget=filters.get("max_budget"), preferred_room_type=filters.get("room_type", ""),
        preferred_furnishing=filters.get("furnishing", ""))
    return preference, {amenity.pk for amenity in filters.get("amenities", [])}


def recommendation_context(tenant, preference, amenity_ids, source="saved", boundary=None):
    # Preserve actual input values, never a browser-supplied score. Bind private
    # preference snapshots to this tenant; Details still enforces listing access.
    return signing.dumps({"tenant": tenant.pk, "source": source, "filters": {
        **{name: str(value) for name, value in (boundary or {}).items() if value is not None},
        "q": preference.preferred_location,
        "max_budget": str(preference.maximum_budget) if preference.maximum_budget is not None else "",
        "room_type": preference.preferred_room_type,
        "furnishing": "" if preference.preferred_furnishing == "any" else preference.preferred_furnishing,
        "amenities": sorted(amenity_ids),
    }}, salt="roomer.preference-match", compress=True)


def valid_boundary(boundary):
    try:
        lat, lon = float(boundary["latitude"]), float(boundary["longitude"])
        return (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
                and int(boundary.get("radius") or 2) in (1, 2, 5))
    except (TypeError, KeyError, ValueError):
        return False


def saved_preference_boundary(preference):
    # Preferences have no persisted radius: use the existing default of 2 km.
    boundary = {"latitude": preference.latitude, "longitude": preference.longitude, "radius": 2}
    if valid_boundary(boundary):
        return boundary
    data, status = lookup_text_location(preference.preferred_location)
    results = list({(item["latitude"], item["longitude"]): item for item in data.get("results", [])}.values())
    if status != 200 or len(results) != 1:
        return {}  # Ambiguous/failed lookup cannot authorize an arbitrary geographic match.
    return {"latitude": results[0]["latitude"], "longitude": results[0]["longitude"], "radius": 2}
