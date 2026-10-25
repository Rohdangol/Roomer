"""One inclusive Haversine boundary for room eligibility and match scoring."""
import math

from django.db.models import ExpressionWrapper, FloatField, Value
from django.db.models.functions import ASin, Cast, Cos, Greatest, Least, Radians, Sin, Sqrt


def room_distance_expression(latitude, longitude):
    latitude, longitude = math.radians(float(latitude)), math.radians(float(longitude))
    room_lat = Radians(Cast("published_revision__latitude", FloatField()))
    room_lon = Radians(Cast("published_revision__longitude", FloatField()))
    half_chord = Sin((room_lat - latitude) / 2.0) ** 2.0 + Cos(Value(latitude)) * Cos(room_lat) * Sin((room_lon - longitude) / 2.0) ** 2.0
    return ExpressionWrapper(12742.0 * ASin(Sqrt(Least(Value(1.0), Greatest(Value(0.0), half_chord)))), output_field=FloatField())


def rooms_within_radius(rooms, latitude, longitude, radius):
    # Keep eligibility in SQL before pagination; <= includes the exact boundary.
    return rooms.filter(published_revision__latitude__isnull=False, published_revision__longitude__isnull=False).annotate(
        distance_km=room_distance_expression(latitude, longitude)).filter(distance_km__lte=float(radius))


def within_radius(distance_km, radius):
    try:
        distance, limit = float(distance_km), float(radius)
        return math.isfinite(distance) and math.isfinite(limit) and 0 <= distance <= limit and limit > 0
    except (TypeError, ValueError):
        return False
