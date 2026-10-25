"""Shared Photon lookups; never change listing content or saved preferences."""
import hashlib
import json
import math
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from listings.services import require_owner
from .permissions import owner_needs_verification


@login_required(login_url="accounts:login")
@require_POST
def tenant_suggestions(request):
    if not request.user.is_active or request.user.is_staff or request.user.role != "tenant":
        return JsonResponse({"error": "An active Tenant account is required."}, status=403)
    query = request.POST.get("q", "").strip()
    if not 2 <= len(query) <= 255:
        return JsonResponse({"error": "Enter 2–255 characters."}, status=400)
    from .search_location import signed_place
    data, status = lookup_text_location(query)
    if status == 200:
        data = {"results": [signed_place(result) for result in data["results"][:5]]}
    return JsonResponse(data, status=status)


@login_required(login_url="accounts:login")
@require_POST
def find_location(request):
    require_owner(request.user)
    if owner_needs_verification(request.user):
        return JsonResponse({"error": "Complete Owner verification before searching."}, status=403)
    endpoint = getattr(settings, "LISTING_GEOCODER_URL", "https://photon.komoot.io/api/")
    if request.POST.get("mode") == "reverse":
        try:
            lat, lon = float(request.POST["latitude"]), float(request.POST["longitude"])
            if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
                raise ValueError
        except (ValueError, KeyError):
            return JsonResponse({"error": "Invalid location coordinates."}, status=400)
        endpoint = getattr(settings, "LISTING_REVERSE_GEOCODER_URL", "https://photon.komoot.io/reverse")
        parameters = {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "limit": 1, "lang": "en"}
    else:
        parts = [request.POST.get(name, "").strip() for name in ("address", "city")]
        if not all(parts) or any(len(value) > 255 for value in parts):
            return JsonResponse({"error": "Enter city and address before searching."}, status=400)
        parameters = {"q": ", ".join(parts), "limit": 5, "lang": "en"}
    data, status = lookup_location(endpoint, parameters)
    return JsonResponse(data, status=status)


def lookup_text_location(location, city=""):
    """Shared forward lookup; authorization belongs to the calling page/view."""
    endpoint = getattr(settings, "LISTING_GEOCODER_URL", "https://photon.komoot.io/api/")
    query = location.strip()
    # Autocomplete display labels include repeated administrative levels. Photon
    # queries use the locality/city portion; keep full returned labels for choices.
    parts = list(dict.fromkeys(part.strip() for part in query.split(",") if part.strip()))
    if len(parts) > 2:
        query = ", ".join(parts[:2])
    if city and city.casefold() not in query.casefold():
        query += ", " + city.strip()
    return lookup_location(endpoint, {"q": query, "limit": 5, "lang": "en"})


def lookup_location(endpoint, parameters):
    """Retain one provider cache, throttle, timeout and parser across both roles."""
    url = endpoint + "?" + urlencode(parameters)
    key = "listing-geocode:v4:" + hashlib.sha256(url.encode()).hexdigest()
    results = cache.get(key)
    if results is not None:
        return {"results": results}, 200
    # A shared cache makes this application-wide across production workers.
    if not cache.add("listing-geocode:throttle", True, timeout=2):
        return {"error": "Location search is busy. Please try again shortly or select the pin manually."}, 429
    try:
        with urlopen(Request(url, headers={"User-Agent": "Roomer-ListingLocation/1.0", "Accept": "application/json"}), timeout=6) as response:
            data = json.loads(response.read(512_000))
        results = []
        for feature in data.get("features", [])[:5]:
            lon, lat = map(float, feature["geometry"]["coordinates"][:2])
            if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
                continue
            properties = feature.get("properties", {})
            values = [str(properties[name]) for name in ("name", "housenumber", "street", "district", "city", "state", "country") if properties.get(name)]
            locality = next((str(properties[name]) for name in ("neighbourhood", "suburb", "district") if properties.get(name)), "")
            display = [str(properties[name]) for name in ("name", "neighbourhood", "suburb", "city", "district", "state", "country") if properties.get(name)]
            results.append({"label": ", ".join(dict.fromkeys(values)) or "Map location", "latitude": lat, "longitude": lon,
                "address": ", ".join(dict.fromkeys(values)), "city": str(properties.get("city", ""))[:100],
                "locality": locality if len(locality) <= 100 else ""})
            results[-1]["display_name"] = ", ".join(dict.fromkeys(display or values))[:255] or "Map location"
        cache.set(key, results, timeout=86400)
        return {"results": results}, 200
    except (URLError, OSError, ValueError, KeyError, TypeError, IndexError):
        return {"error": "Location search is unavailable. Try again or select a pin on the map; your entered details are retained."}, 503
