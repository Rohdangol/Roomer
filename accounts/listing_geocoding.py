"""Explicit Owner address searches; never change or save listing content here."""
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
    url = endpoint + "?" + urlencode(parameters)
    key = "listing-geocode:v3:" + hashlib.sha256(url.encode()).hexdigest()
    results = cache.get(key)
    if results is not None:
        return JsonResponse({"results": results})
    # A shared cache makes this application-wide across production workers.
    if not cache.add("listing-geocode:throttle", True, timeout=2):
        return JsonResponse({"error": "Location search is busy. Please try again shortly or select the pin manually."}, status=429)
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
            results.append({"label": ", ".join(dict.fromkeys(values)) or "Map location", "latitude": lat, "longitude": lon,
                "address": ", ".join(dict.fromkeys(values)), "city": str(properties.get("city", ""))[:100],
                "locality": locality if len(locality) <= 100 else ""})
        cache.set(key, results, timeout=86400)
        return JsonResponse({"results": results})
    except (URLError, OSError, ValueError, KeyError, TypeError, IndexError):
        return JsonResponse({"error": "Location search is unavailable. Try again or select a pin on the map; your entered details are retained."}, status=503)
