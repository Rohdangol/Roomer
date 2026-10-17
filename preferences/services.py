from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from listings.models import Amenity
from .models import PreferredAmenity, TenantPreference


@transaction.atomic
def save_tenant_preference(actor, details, amenity_ids=(), coordinates_selected=False):
    if not actor.is_authenticated or not actor.is_active or actor.is_staff or actor.role != "tenant":
        raise PermissionDenied("An active tenant account is required.")
    # request.user may be lazy; use the configured model to lock the account before first save.
    get_user_model().objects.select_for_update().get(pk=actor.pk)
    preference = TenantPreference.objects.filter(tenant=actor).first() or TenantPreference(tenant=actor)
    fields = {"preferred_location", "latitude", "longitude", "maximum_budget", "preferred_room_type", "preferred_furnishing"}
    details = dict(details)
    details.setdefault("latitude", None)
    details.setdefault("longitude", None)
    if set(details) != fields:
        raise ValidationError("Provide all required preference fields and no account/status fields.")
    # A renamed area must not retain an old map point unless explicitly selected anew.
    same_point = (details["latitude"], details["longitude"]) == (preference.latitude, preference.longitude)
    area_changed = details["preferred_location"].strip().casefold() != preference.preferred_location.strip().casefold()
    if preference.pk and area_changed and same_point and not coordinates_selected:
        details["latitude"] = details["longitude"] = None
    for name, value in details.items():
        setattr(preference, name, value)
    ids = set(amenity_ids)
    if Amenity.objects.filter(pk__in=ids).count() != len(ids):
        raise ValidationError("Choose existing amenities.")
    preference.full_clean()
    preference.save()
    preference.amenity_links.all().delete()
    PreferredAmenity.objects.bulk_create([PreferredAmenity(preference=preference, amenity_id=value) for value in ids])
    return preference
