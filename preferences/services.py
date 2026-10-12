from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from listings.models import Amenity
from .models import PreferredAmenity, TenantPreference


@transaction.atomic
def save_tenant_preference(actor, details, amenity_ids=()):
    if not actor.is_authenticated or not actor.is_active or actor.is_staff or actor.role != "tenant":
        raise PermissionDenied("An active tenant account is required.")
    # Lock the account even for the first save, before a preference row exists.
    type(actor).objects.select_for_update().get(pk=actor.pk)
    preference = TenantPreference.objects.filter(tenant=actor).first() or TenantPreference(tenant=actor)
    fields = {"preferred_location", "latitude", "longitude", "maximum_budget", "preferred_room_type", "preferred_furnishing"}
    if set(details) != fields:
        raise ValidationError("Provide all required preference fields and no account/status fields.")
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
