"""Available neighbourhood groups and matching share whitespace/case normalization."""
import re

from django.db.models import Count


def normalized_location(value):
    return " ".join(value.split()).casefold()


def location_pattern(value):
    return r"^\s*" + r"\s+".join(re.escape(part) for part in value.split()) + r"\s*$"


def available_neighbourhoods(listings):
    groups = {}
    rows = listings.values("published_revision__locality", "published_revision__city").annotate(room_count=Count("pk")).order_by("published_revision__locality", "published_revision__city")
    for row in rows:
        area = " ".join(row["published_revision__locality"].split())
        city = " ".join(row["published_revision__city"].split())
        if not area:
            continue
        key = (normalized_location(area), normalized_location(city))
        if key not in groups:
            groups[key] = {"published_revision__locality": area, "published_revision__city": city, "room_count": 0}
        groups[key]["room_count"] += row["room_count"]
    return sorted(groups.values(), key=lambda item: (-item["room_count"],
        normalized_location(item["published_revision__locality"]), normalized_location(item["published_revision__city"])))
